"""Explicit, opt-in model check using invented data only. Never loads the workbook."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values
from copilot.agent import assess
from copilot.llm import ModelConfig
from copilot.summary import build_summary
from copilot.summary_llm import generate_summary

SYNTHETIC = {
    'choice': [('买家', '瓶子泵头坏了，我发过照片了。'), ('客服', '可以换货或者退款，选哪种？'),
               ('买家', '那换吧，不退款。'), ('客服', '登记好了，48小时内发出。')],
    'partial_payment': [('买家', '退款和运费补偿都还没收到。'), ('客服', '商品退款和运费补偿分开处理，我去核实。'),
                        ('买家', '商品退款收到了，运费补偿还没收到，别漏了。')],
    'conflict': [('客服', '系统工单显示换货已经完成。'), ('买家', '但换来的东西我根本没收到！'),
                 ('客服', '之前照片和地址都已收到，我核实物流。')],
    'invoice': [('买家', '我想开电子发票，抬头和税号已经在订单备注提供。'),
                ('客服', '信息已收到，申请已经登记。'), ('买家', '那开好发我，别再让我填一遍了。')],
    'adverse': [('买家', '我用过产品后脸上红肿刺痛，现在在医院。'),
                ('客服', '已登记转交专业人员跟进，回访还未安排。'),
                ('买家', '我已经提交了相关资料，希望尽快有人联系。')],
}


def synthetic_case(name):
    return {'session_id': 'SYNTHETIC_' + name, 'cutoff': '2026-01-01 10:06:00', 'orders': [], 'tickets': [],
            'messages': [{'message_id': str(i), '角色': role, 'message_text': text, '发送时间': f'2026-01-01 10:0{i}:00'}
                         for i, (role, text) in enumerate(SYNTHETIC[name])]}


def run(config, directory):
    directory.mkdir(parents=True, exist_ok=True)
    def check(name):
        case = synthetic_case(name)
        summary = build_summary([case])
        summary['risk'] = assess(case)
        try:
            output = generate_summary(summary, config)
            (directory / (name + '.json')).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
            return {'case': name, 'schema_and_evidence_pass': True, 'risk_preserved': output['risk'] == summary['risk'],
                    'human_semantic_review': 'required'}
        except Exception as error:
            return {'case': name, 'schema_and_evidence_pass': False, 'error_type': type(error).__name__}
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(check, SYNTHETIC))
    (directory / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='明确允许调用已配置的模型接口；只发送合成案例')
    parser.add_argument('--config', type=Path, default=ROOT / '.env')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts' / 'summary-live-check')
    args = parser.parse_args()
    if not args.live:
        parser.error('真实调用需要 --live；不会自动发送比赛资料。')
    values = dotenv_values(args.config)
    config = ModelConfig(values.get('LLM_BASE_URL', ''), values.get('LLM_MODEL', ''), values.get('LLM_API_KEY', ''))
    outcomes = run(config, args.output)
    print(json.dumps(outcomes, ensure_ascii=False))
    sys.exit(0 if all(r['schema_and_evidence_pass'] for r in outcomes) else 1)
