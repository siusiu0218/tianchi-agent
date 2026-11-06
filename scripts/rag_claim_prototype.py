"""Local adversarial examples for free-text claim review; no model/API calls."""
from dataclasses import replace
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copilot.rag_claim_prototype import Evidence, audit


def run():
    source = Evidence('C1', 'current_chat', 'SYN_CURRENT', '2026-05-01T10:00:00+08:00',
                      (('refund_amount', '40'), ('historical_dispatch_hours', '48'),
                       ('staff_reported_dispatch', 'true')))
    business = Evidence('B1', 'current_business', source.session, source.available_at,
                        (('replacement_dispatched', 'true'),))
    evidence = [source, business, replace(source, id='OLD', origin='case', session='SYN_OTHER'),
                replace(source, id='FUTURE', available_at='2026-06-01T00:00:00+08:00'),
                replace(source, id='POLICY', origin='policy')]
    def claim(field, value, ref='C1'):
        return {'field': field, 'value': value, 'refs': [ref]}
    rows = [
        ('转述当前金额', '此前沟通的退款金额为40元，实际进度需核实。', [claim('refund_amount','40')], False),
        ('旧案例金额', '退款40元。', [claim('refund_amount','40','OLD')], True),
        ('政策不能证明本单退款', '退款40元。', [claim('refund_amount','40','POLICY')], True),
        ('未来来源', '退款40元。', [claim('refund_amount','40','FUTURE')], True),
        ('错误引用', '退款40元。', [claim('refund_amount','40','MISSING')], True),
        ('数值在上下文出现但用途错误', '补偿40元。', [claim('compensation_amount','40')], True),
        ('声明退款但正文写补偿', '补偿40元。', [claim('refund_amount','40')], True),
        ('正负号不能被忽略', '退款-40元。', [claim('refund_amount','40')], True),
        ('中文逐字数字', '此前提到四〇元。', [claim('refund_amount','40')], False),
        ('未申报金额', '退款99元。', [], True),
        ('中文金额污染', '退款九十九元。', [], True),
        ('全角金额污染', '退款９９元。', [], True),
        ('金额改写', '退款99元。', [claim('refund_amount','40')], True),
        ('中文时限正确转述', '客服此前提到四十八小时，实际进度需核实。', [claim('historical_dispatch_hours','48')], False),
        ('天与小时换算', '客服此前提到两天，实际进度需核实。', [claim('historical_dispatch_hours','48')], False),
        ('单位错配', '客服此前提到48天。', [claim('historical_dispatch_hours','48')], True),
        ('时限变成新承诺', '保证48小时内发货。', [claim('historical_dispatch_hours','48')], True),
        ('聊天声称不能作为执行凭证', '已经发货。', [claim('replacement_dispatched','true')], True),
        ('执行凭证存在', '已经发货。', [claim('replacement_dispatched','true','B1')], False),
        ('声明正确但正文过度推断', '已经签收。', [claim('replacement_dispatched','true','B1')], True),
        ('没有声明的执行状态', '已退款99元。', [], True),
        ('医学诊断', '诊断为过敏。', [], True),
        ('一般核实措辞', '我会协助核实处理进展。', [], False),
        # Deliberate known limitation: no pattern hit is NOT semantic approval.
        ('隐含到账措辞仍必须人工审阅', '钱已经回到您的口袋里了。', [], False),
    ]
    results = []
    for name, text, claims, blocked in rows:
        output = {'context_id': 'snapshot', 'sentences': [{'text': text, 'claims': claims}]}
        result = audit(output, evidence, session=source.session, cutoff='2026-05-05T00:00:00+08:00',
                       context_id='snapshot', draft='原稿保留')
        assert (result['status'] == 'blocked') == blocked, (name, result)
        assert result['draft'] == '原稿保留' and result['auto_approved'] is False
        assert result.get('semantic_support_verified') is False
        results.append({'name': name, 'status': result['status'], 'issues': result['issues'], 'pass': True})
    # Same amount in another sentence cannot support an unreferenced assertion.
    output = {'context_id': 'snapshot', 'sentences': [
        {'text': '此前提到40元。', 'claims': [claim('refund_amount','40')]},
        {'text': '退款40元。', 'claims': []}]}
    result = audit(output, evidence, session=source.session, cutoff='2026-05-05T00:00:00+08:00', context_id='snapshot')
    assert 'sentence_2:unsupported_number_or_unit' in result['issues']
    results.append({'name': '逐句引用不能借用其他句的数字', 'pass': True})
    for text, blocked in [('我会核实。', True), ('您反馈的不适需要优先核实，建议由专业售后处理人员跟进。', False)]:
        output = {'context_id': 'snapshot', 'sentences': [{'text': text, 'claims': []}]}
        result = audit(output, evidence, session=source.session, cutoff='2026-05-05T00:00:00+08:00', context_id='snapshot', risk_level='P0')
        assert (result['status'] == 'blocked') == blocked and result['risk_level'] == 'P0'
        results.append({'name': 'P0必答检查:' + text, 'pass': True})
    for name, output in [
        ('过期快照', {'context_id': 'old', 'sentences': []}),
        ('额外执行指令', {'context_id': 'snapshot', 'sentences': [], 'action': 'refund'}),
        ('没有句子', {'context_id': 'snapshot', 'sentences': []}),
        ('非法正文类型', {'context_id': 'snapshot', 'sentences': [{'text': 123, 'claims': []}]}),
        ('畸形引用', {'context_id': 'snapshot', 'sentences': [{'text': '退款40元', 'claims': [claim('refund_amount','40',123)]}]}),
    ]:
        result = audit(output, evidence, session=source.session, cutoff='2026-05-05T00:00:00+08:00', context_id='snapshot', draft='原稿保留')
        assert result['status'] == 'blocked' and result['draft'] == '原稿保留' and not result['suggestion']
        results.append({'name': name, 'pass': True})
    return {'passed': len(results), 'total': len(results), 'results': results,
            'boundary': 'Known-error detection only; every non-blocked response still requires human semantic review.', 'live_api_calls': 0}


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2) if '--json' in sys.argv else
          f"事实审阅检查 {result['passed']}/{result['total']} 通过。未发现已知错误的正文仍待人工审阅，不自动批准。")
