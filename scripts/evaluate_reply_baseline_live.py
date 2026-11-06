"""Four authorized MOCK checkpoints, one request each; default is offline preview."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlparse
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from copilot.data import ExcelProvider, DEFAULT_SOURCE
from copilot.agent import assess
from copilot.llm import ModelConfig
from copilot.reply_llm import PROMPT as REPLY_PROMPT, redact
from desktop.config import load_model_settings, read_settings

PROMPT = REPLY_PROMPT + '''
本次为离线业务样本评测，不执行业务操作。覆盖上面的输出格式要求，输出且只输出JSON：
{"focus":"当前处理事项","stage":"当前阶段","known_information":["已提供的信息"],"missing_information":["仍需要了解的信息"],"reply":"下一条回复"}。
自己从消息判断当前事项和阶段，不套用所有场景都换货的流程。客户已接受方案时跟进原安排，变更方案才重新确认。
先回应不适，只询问当前处理必要且尚未提供的信息；已有就医、资料、账户或用药信息不重复索取。
输入只有截止点可见聊天与确定性风险，无最新业务执行凭证或正式政策。历史承诺只能视为此前说法，不能重新保证。
'''


def contexts():
    provider = ExcelProvider()
    rows = []
    for session, index in [('S00001', 0), ('S00001', 4), ('S00268', 0), ('S00268', 8)]:
        messages = provider.messages(session)
        case = provider.get_case(session, messages[index]['发送时间'])
        visible = []
        for i, msg in enumerate(case['messages'], 1):
            text = redact(msg['message_text'])
            # Preserve that details were supplied without sending account routes or drug names.
            if session == 'S00268' and msg['角色'] == '买家' and '医生开了' in text:
                text = '已说明收款账户信息，并提供医生开的用药信息。急。'
            text = text.replace('欣欣', '[客服]').replace('12315', '[投诉渠道]')
            visible.append({'ref': f'M{i}', 'role': msg['角色'], 'text': text,
                            'image_message': msg.get('内容类型') == '图片'})
        rows.append({'id': session + '_' + str(index), 'session': session,
                     'cutoff': case['cutoff'],
                     'context': {'messages': visible, 'risk_level': assess(case)['level'],
                                 'attachment_notice': '未提供图片或医疗附件原件；不得声称看过附件。'}})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to((ROOT / '.scratch').resolve()):
        parser.error('Output must be inside ignored .scratch')
    rows = contexts()
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'requests.json').write_text(json.dumps({'prompt': PROMPT, 'cases': rows}, ensure_ascii=False, indent=2), encoding='utf-8')
    if not args.live:
        print('Offline preview saved; 0 requests')
        return
    settings, key = load_model_settings(read_settings())
    config = ModelConfig(settings.get('base_url', ''), settings.get('model', ''), key)
    config.validate()
    print(json.dumps({'model': config.model, 'host': urlparse(config.base_url).hostname, 'requests': 4}), flush=True)
    source_hash = hashlib.sha256(DEFAULT_SOURCE.read_bytes()).hexdigest()
    for row in rows:
        payload = {'model': config.model, 'temperature': 0, 'max_tokens': 1600,
                   'response_format': {'type': 'json_object'},
                   'messages': [{'role': 'system', 'content': PROMPT},
                                {'role': 'user', 'content': json.dumps(row['context'], ensure_ascii=False)}]}
        if config.model.lower().startswith('qwen3'):
            payload['enable_thinking'] = False
        result = {'id': row['id'], 'model': config.model, 'host': urlparse(config.base_url).hostname,
                  'source_sha256': source_hash, 'prompt_sha256': hashlib.sha256(PROMPT.encode()).hexdigest(),
                  'request_sha256': hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
                  'temperature': 0, 'max_tokens': 1600, 'attempts': 1, 'human_review': 'pending'}
        start = time.monotonic()
        try:
            response = requests.post(config.base_url.rstrip('/') + '/chat/completions',
                                     headers={'Authorization': 'Bearer ' + config.api_key}, json=payload,
                                     timeout=(5, 45), allow_redirects=False)
            result['http_status'] = response.status_code
            response.raise_for_status()
            envelope = response.json()
            result['usage'] = envelope.get('usage')
            result['returned_model'] = envelope.get('model')
            result['finish_reason'] = envelope['choices'][0].get('finish_reason')
            result['content'] = envelope['choices'][0]['message']['content']
            parsed = json.loads(result['content'])
            if set(parsed) != {'focus', 'stage', 'known_information', 'missing_information', 'reply'}:
                raise ValueError('Unexpected output schema')
            if not all(isinstance(parsed[k], str) for k in ('focus', 'stage', 'reply')):
                raise ValueError('Invalid text fields')
            if not all(isinstance(parsed[k], list) and all(isinstance(v, str) for v in parsed[k])
                       for k in ('known_information', 'missing_information')):
                raise ValueError('Invalid information lists')
            result['parsed'] = parsed
            result['status'] = 'structure_valid_semantics_pending'
        except Exception as exc:
            result['status'] = 'failed'
            result['error_type'] = type(exc).__name__
        result['elapsed_seconds'] = round(time.monotonic() - start, 3)
        (args.output / (row['id'] + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(row['id'], result['status'], result['elapsed_seconds'], flush=True)
    assert hashlib.sha256(DEFAULT_SOURCE.read_bytes()).hexdigest() == source_hash


if __name__ == '__main__':
    main()
