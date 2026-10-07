"""Export synthetic calibration packets; never calls a model or approves text."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from copilot.rag_workflow_prototype import ReviewWorkflow
from scripts.rag_workflow_prototype import fixtures, fixed, annotated, contaminated, missed


DIMENSIONS = ('source_support', 'numbers_units', 'speaker_and_time', 'execution_state',
              'commitment_authority', 'risk_handling', 'relevance')


def packets():
    result = []
    for session in ('SYN_A', 'SYN_B'):
        for name, mode, model in [('fixed', 'fixed', fixed), ('annotated', 'annotated', annotated),
                                  ('contaminated', 'annotated', contaminated),
                                  ('missed', 'annotated', missed)]:
            flow = ReviewWorkflow(fixtures())
            flow.switch(session)
            token = flow.begin(mode)
            assert flow.complete(token, model)
            view = flow.view()
            review = view['review']
            rows = [{'sentence_id': str(i), 'text': sentence['text'],
                     'model_claims': sentence['claims'], 'verified_refs': [],
                     'ratings': dict.fromkeys(DIMENSIONS), 'severity': None,
                     'reason': None, 'corrected_text': None}
                    for i, sentence in enumerate(review['candidate']['sentences'], 1)]
            result.append({'schema_version': 2, 'id': session + '_' + name, 'synthetic': True,
                           'purpose': 'reviewer_calibration_not_model_evaluation',
                           'context_id': token, 'preview_id': review['preview_id'],
                           'snapshot': view, 'sentence_reviews': rows,
                           'response_review': {'required_items': [], 'missing_items': [],
                                               'contradictions': [], 'overall': None},
                           'human_review': {'status': 'unreviewed', 'reviewer': None,
                                            'reviewed_at': None, 'adjudicator': None}})
    return result


def render(packet):
    view = packet['snapshot']
    lines = [f"# 核对包 {packet['id']}", '',
             '合成校准样例；尚未人工审核；不能计入真实模型效果。', '',
             f"预览标识：`{packet['preview_id']}`", '',
             f"截止点：`{view['cutoff']}`（含时区）；仅针对该快照核对。", '',
             f"规则状态：{view['status']}；风险：{view['risk']['level']}。规则结果仅供参考。", '',
             '## 当前原文', '']
    for msg in view['messages']:
        lines.append(f"- {msg['message_id']} | {msg['发送时间']} | {msg['角色']}：{msg['message_text']}")
    lines += ['', '## 当前业务快照', '',
              '以下记录由调用方提供；空列表仅表示本快照没有记录，不证明业务未发生。缺少字段表示未提供。', '']
    for field, title in [('orders', '订单'), ('tickets', '工单')]:
        records = view['case_snapshot'].get(field)
        lines += [f'### {title}', '',
                  '未提供该字段。' if records is None else
                  ('本快照记录为空。' if records == [] else
                   '```json\n' + json.dumps(records, ensure_ascii=False, indent=2) + '\n```'), '']
    lines += ['## 逐句核对', '']
    for row in packet['sentence_reviews']:
        lines += [f"### 句 {row['sentence_id']}", '', row['text'], '',
                  f"模型声明（待核实）：{json.dumps(row['model_claims'], ensure_ascii=False)}", '',
                  '- 原文依据及 message ID：待填写',
                  '- 来源支持 / 数字单位 / 说话人及时间 / 执行状态 / 承诺权限 / 风险处理 / 相关性：待逐项填写',
                  '- 严重程度、理由及建议改文：待填写', '']
    lines += ['## 整体核对', '', '- 当前必须回应事项及依据：待填写',
              '- 遗漏、矛盾及整体结论：待填写', '- 审核人、时间及争议复核：待填写', '',
              '来源详情、规则发现和固定片段引用见同名 JSON 的 snapshot；不要只核对模型自行列出的声明。', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New directory; existing paths are refused')
    args = parser.parse_args()
    # Refuse overwriting any existing review, including human annotations.
    args.output.mkdir(parents=True, exist_ok=False)
    data = packets()
    hashes = {}
    for packet in data:
        for suffix, content in [('.json', json.dumps(packet, ensure_ascii=False, indent=2)),
                                ('.md', render(packet))]:
            path = args.output / (packet['id'] + suffix)
            path.write_text(content, encoding='utf-8')
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {'schema_version': 2, 'created_at': datetime.now(timezone.utc).isoformat(),
                'packets': len(data), 'human_reviewed': 0, 'live_model_calls': 0,
                'independent_test_cases': 0, 'initial_file_sha256': hashes}
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in manifest.items() if k != 'initial_file_sha256'}))


if __name__ == '__main__':
    main()
