"""Integrated local terminal demo. All data and model responses are synthetic.

python scripts/rag_workflow_prototype.py
python scripts/rag_workflow_prototype.py --check [--json]
"""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copilot.rag_claim_prototype import Evidence
from copilot.rag_workflow_prototype import ReviewWorkflow
from scripts.rag_prototype import scenarios


def fixtures():
    seed = scenarios()[0]
    states = {}
    for name in ('SYN_A', 'SYN_B'):
        query = replace(seed['query'], session=name, group=name + '_GROUP')
        messages = [
            {'message_id': name + '/M1', '发送时间': '2026-05-05T10:18:00+08:00', '角色': '买家',
             'message_text': '商品破损，需要处理。' if name == 'SYN_A' else '商品破损，用后红肿刺痛，需要处理。'},
            {'message_id': name + '/M2', '发送时间': '2026-05-05T10:24:00+08:00', '角色': '客服',
             'message_text': '为您提出换货安排，预计48小时发出。'},
            {'message_id': name + '/M3', '发送时间': query.at, '角色': '买家', 'message_text': '行，那麻烦尽快。'},
        ]
        states[name] = {'case': {'session_id': name, 'cutoff': query.at, 'messages': messages,
                                'orders': [], 'tickets': []}, 'query': query,
                        'documents': seed['documents'], 'draft': name + ' 的手写草稿',
                        'evidence': [Evidence(name + '/M2', 'current_chat', name, messages[1]['发送时间'],
                                              (('historical_dispatch_hours', '48'),))]}
    return states


def fixed(context):
    return {'context_id': context['context_id'], 'segment_ids': context['required_ids'][:]}


def annotated(context):
    source = context['current_assertions'][0]['id']
    rows = [{'text': '此前客服预计48小时发出，具体进度仍需核实。',
             'claims': [{'field': 'historical_dispatch_hours', 'value': '48', 'refs': [source]}]},
            {'text': '我会协助核对此前沟通的换货安排及实际进度。', 'claims': []}]
    if context['risk_level'] == 'P0':
        rows.insert(0, {'text': '您反馈的不适需要优先核实，建议由专业售后处理人员跟进。', 'claims': []})
    return {'context_id': context['context_id'], 'sentences': rows}


def contaminated(context):
    return {'context_id': context['context_id'], 'sentences': [
        {'text': '已退款99元，保证48小时内发货。', 'claims': []}]}


def missed(context):
    return {'context_id': context['context_id'], 'sentences': [
        {'text': '钱已经回到您的口袋里了。', 'claims': []}]}


def run_checks():
    checks = []
    def check(name, ok):
        assert ok, name
        checks.append({'name': name, 'pass': True})
    flow = ReviewWorkflow(fixtures())
    original = flow.view()['draft']
    check('原稿在未生成时保留', flow.view()['status'] == 'idle')
    token = flow.begin()
    check('开始生成不改草稿', flow.view()['status'] == 'generating' and flow.view()['draft'] == original)
    check('固定预览串接检索与审阅', flow.complete(token, fixed))
    view = flow.view()
    check('固定预览仍待人工确认', view['status'] == 'needs_human_review' and view['draft'] == original)
    check('来源与段落引用保留', view['retrieval']['hits'] and view['review']['segment_citations'])
    check('未写核对备注不能采纳', not flow.adopt(view['review']['preview_id'], actor='测试员', note=''))
    check('错误预览标识不能采纳', not flow.adopt('wrong', actor='测试员', note='核对'))
    check('明确人工动作可采纳本地草稿', flow.adopt(view['review']['preview_id'], actor='测试员', note='合成测试中逐项核对'))
    check('采纳保留旧稿且没有外发动作', original in flow.view()['draft_history'] and not flow.view()['business_actions'])
    check('同一预览不能重复采纳', not flow.adopt(view['review']['preview_id'], actor='测试员', note='核对'))

    flow = ReviewWorkflow(fixtures())
    token = flow.begin('annotated')
    check('自由文字和声明进入同一流程', flow.complete(token, annotated))
    view = flow.view()
    check('声明引用可在同处审阅', view['status'] == 'needs_human_review'
          and view['review']['audit']['citations'][0]['refs'] == ['SYN_A/M2'])
    flow.reject()
    check('人工驳回保留原稿', flow.view()['status'] == 'rejected' and flow.view()['draft'] == original)
    token = flow.begin('annotated')
    flow.complete(token, contaminated)
    view = flow.view()
    check('旧金额时限和执行宣称被阻断', view['status'] == 'blocked' and view['review']['audit']['issues'])
    check('被阻断结果不能点采纳', not flow.adopt(view['review']['preview_id'], actor='测试员', note='尝试绕过'))
    token = flow.begin('annotated')
    flow.complete(token, missed)
    check('已知漏检仍停在人工审阅', flow.view()['status'] == 'needs_human_review'
          and flow.view()['review']['audit']['auto_approved'] is False and flow.view()['draft'] == original)

    for name, change in [
        ('生成期间编辑草稿', lambda f: f.edit_draft('人工新稿')),
        ('生成期间切换会话', lambda f: f.switch('SYN_B')),
        ('切走再切回也使旧任务过期', lambda f: (f.switch('SYN_B'), f.switch('SYN_A'))),
        ('草稿改动再还原也使旧任务过期', lambda f: (f.edit_draft('临时'), f.edit_draft(original))),
        ('生成期间撤销来源审核', lambda f: f.update_sources(documents=[replace(fixtures()['SYN_A']['documents'][0], review='pending')])),
        ('生成期间变更事实标注', lambda f: f.update_sources(evidence=[])),
    ]:
        flow = ReviewWorkflow(fixtures())
        token = flow.begin()
        def changing(context):
            change(flow)
            return fixed(context)
        check(name, not flow.complete(token, changing) and flow.view()['status'] == 'stale')
    flow = ReviewWorkflow(fixtures())
    first, second = flow.begin(), flow.begin()
    check('旧任务不覆盖新任务', not flow.complete(first, fixed) and flow.complete(second, fixed))
    preview_id = flow.view()['review']['preview_id']
    flow.edit_draft('人工新稿')
    check('展示后编辑阻止旧预览采纳', not flow.adopt(preview_id, actor='测试员', note='核对') and flow.view()['draft'] == '人工新稿')
    flow.switch('SYN_B')
    flow.edit_draft('B独立草稿')
    flow.switch('SYN_A')
    check('会话草稿彼此隔离', flow.view()['draft'] == '人工新稿')
    flow.switch('SYN_B')
    token = flow.begin('annotated')
    flow.complete(token, annotated)
    check('P0跨整个流程保留', flow.view()['risk']['level'] == 'P0' and '不适' in flow.view()['review']['audit']['suggestion'])
    flow.complete(flow.begin('annotated'), missed)
    check('遗漏P0内容不能采纳', flow.view()['status'] == 'blocked')
    def fail(context):
        raise TimeoutError('synthetic timeout')
    check('模型异常不毁坏原稿', not flow.complete(flow.begin(), fail)
          and flow.view()['status'] == 'error' and flow.view()['draft'] == 'B独立草稿')
    flow = ReviewWorkflow(fixtures())
    flow.update_sources(documents=[])
    flow.complete(flow.begin(), fixed)
    check('无命中降级核实仍待人工', flow.view()['retrieval']['status'] == 'no_match' and flow.view()['status'] == 'needs_human_review')
    # Exposed state is a copy; changing the viewer cannot replace approved text.
    view = flow.view()
    view['review']['audit']['suggestion'] = '已退款99元'
    check('外部查看不能篡改内部预览', '99' not in flow.view()['review']['audit']['suggestion'])
    invalid = replace(fixtures()['SYN_A']['evidence'][0], id='NONEXISTENT')
    try:
        flow.update_sources(evidence=[invalid])
    except ValueError:
        check('不存在的当前消息证据不能载入', flow.view()['status'] == 'stale')
    else:
        raise AssertionError('Invalid evidence accepted')
    return {'passed': len(checks), 'total': len(checks), 'results': checks,
            'synthetic_only': True, 'live_model_calls': 0, 'business_actions': 0}


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    if '--check' in sys.argv:
        result = run_checks()
        print(json.dumps(result, ensure_ascii=False, indent=2) if '--json' in sys.argv else
              f"本地完整流程检查 {result['passed']}/{result['total']} 通过。合成数据，无真实模型或发送操作。")
        return
    flow = ReviewWorkflow(fixtures())
    notice = ''
    while True:
        view = flow.view()
        review = view['review']
        print('\033[2J\033[H', end='')
        print('共情副驾本地 RAG 流程 · 全部为合成演示 · 退出后不保存')
        print(f"会话：{view['session']}  风险：{view['risk']['level']}  状态：{view['status']}")
        print('原稿/当前草稿：' + view['draft'])
        print('检索：' + view['retrieval']['status'])
        if review:
            response = review['candidate']
            rows = response.get('sentences', []) if isinstance(response, dict) else []
            print('待核对候选：' + ''.join(row.get('text', '') for row in rows if isinstance(row, dict)))
            print('已知问题：' + ', '.join(review['audit']['issues']))
            print('未发现已知错误也不等于事实正确；采用前需人工核对。')
        if notice:
            print(notice)
        print('[g] 固定预览 [f] 自由文字样例 [b] 污染样例 [m] 已知漏检样例')
        print('[e] 查看消息/来源/引用 [d] 修改草稿 [s] 切会话 [u] 清空检索资料')
        print('[a] 核对后采用为本地草稿 [r] 驳回 [q] 退出')
        try:
            command = input('> ').strip().lower()
            notice = ''
            if command == 'q':
                return
            if command in {'g', 'f', 'b', 'm'}:
                model = {'g': fixed, 'f': annotated, 'b': contaminated, 'm': missed}[command]
                flow.complete(flow.begin('fixed' if command == 'g' else 'annotated'), model)
            elif command == 'd':
                flow.edit_draft(input('输入新的草稿：'))
            elif command == 's':
                flow.switch('SYN_B' if view['session'] == 'SYN_A' else 'SYN_A')
            elif command == 'u':
                flow.update_sources(documents=[])
            elif command == 'r':
                flow.reject()
            elif command == 'e':
                print(json.dumps(view, ensure_ascii=False, indent=2))
                input('Enter 返回')
            elif command == 'a':
                if view['status'] != 'needs_human_review':
                    notice = '当前没有可采纳的待审阅预览。'
                else:
                    note = input('确认逐句核对后填写核对备注（仅采用到本地草稿）：')
                    adopted = flow.adopt(review['preview_id'], actor='本地演示用户', note=note)
                    notice = '已采用到本地草稿，未发送；旧稿保留在本次会话记录中。' if adopted else '未采用：备注为空或预览已失效。'
        except EOFError:
            return
        except ValueError as error:
            notice = str(error)


if __name__ == '__main__':
    main()
