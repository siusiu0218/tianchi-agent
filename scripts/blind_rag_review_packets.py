"""Blind existing v2 synthetic packets locally; no model calls or approvals."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import secrets


def project(packet, blind_id):
    if packet.get('schema_version') != 2 or packet.get('synthetic') is not True:
        raise ValueError('Only v2 synthetic calibration packets are supported')
    view = packet['snapshot']
    sources = [{'id': hit['id'], 'version': hit['version'], 'allowed_use': hit['allowed_use'],
                'source_records': hit['evidence_for_review_only']}
               for hit in view['retrieval']['hits']]
    return {'id': blind_id, 'notice': '合成校准材料；待人工审核；不是独立效果评测。',
            'evidence': {'cutoff': view['cutoff'], 'case': deepcopy(view['case_snapshot']),
                         'reference_sources': sources},
            'candidate': [{'sentence_id': row['sentence_id'], 'text': row['text']}
                          for row in packet['sentence_reviews']],
            'human_review': {'status': 'unreviewed', 'reviewer': None, 'reviewed_at': None,
                             'required_items': [], 'sentence_findings': [],
                             'missing_items': [], 'overall': None}}


def render(packet):
    lines = [f"# 候选 {packet['id']}", '', packet['notice'], '',
             '先独立列出原文中的必答项，再逐句核对候选。空业务记录不证明业务未发生。', '',
             '## 可核对证据', '', '```json',
             json.dumps(packet['evidence'], ensure_ascii=False, indent=2), '```', '',
             '## 候选回复与逐句核对', '']
    for row in packet['candidate']:
        lines += [f"### 句 {row['sentence_id']}", '', row['text'], '',
                  '- 来源原话及引用：待填写',
                  '- 来源支持、数字单位、说话人及时间、执行状态、承诺权限、风险处理、相关性：待逐项填写',
                  '- 严重程度、理由及修改建议：待填写', '']
    lines += ['## 整体核对', '', '- 原文必答项及遗漏：待填写',
              '- 整体结论：待填写', '- 审核人、时间及争议复核：待填写', '',
              '维度取值 pass / fail / uncertain / not_applicable；不适用须解释。',
              '严重程度 critical / major / minor / none；整体 acceptable / revise / reject / uncertain。',
              '未填写或 uncertain 不当作通过。任何结论均不授权发送或执行业务操作。', '']
    return '\n'.join(lines)


def export(source, output):
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    inputs = []
    # Only manifest-bound top-level synthetic packets; no arbitrary path reads.
    for name, expected in manifest['initial_file_sha256'].items():
        if Path(name).name != name or '/' in name or '\\' in name:
            raise ValueError('Manifest paths must be simple filenames')
        raw = (source / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('Source changed since export: ' + name)
        if name.endswith('.json'):
            inputs.append((name, expected, json.loads(raw)))
    if not inputs or len(inputs) != manifest['packets']:
        raise ValueError('Packet count mismatch')
    secrets.SystemRandom().shuffle(inputs)
    projected, mapping, groups = [], [], {}
    for i, (name, source_hash, packet) in enumerate(inputs, 1):
        public = project(packet, f'R{i:03d}')
        case = public['evidence']['case']
        group = (case['session_id'], public['evidence']['cutoff'])
        canonical = json.dumps(public['evidence'], ensure_ascii=False, sort_keys=True)
        if group in groups and groups[group] != canonical:
            raise ValueError('Compared candidates do not have identical review evidence')
        groups[group] = canonical
        projected.append(public)
        mapping.append({'blind_id': public['id'], 'source_file': name,
                        'source_sha256': source_hash, 'source_id': packet['id'],
                        'preview_id': packet['preview_id']})
    # No overwrite of reviewer work. All inputs validated before creating output.
    output.mkdir(parents=True, exist_ok=False)
    reviewer = output / 'reviewer'
    coordinator = output / 'coordinator'
    reviewer.mkdir()
    coordinator.mkdir()
    hashes = {}
    for packet in projected:
        for suffix, content in [('.json', json.dumps(packet, ensure_ascii=False, indent=2)),
                                ('.md', render(packet))]:
            path = reviewer / (packet['id'] + suffix)
            path.write_text(content, encoding='utf-8')
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    key = {'mapping': mapping, 'reviewer_initial_sha256': hashes,
           'human_reviewed': 0, 'live_model_calls': 0}
    (coordinator / 'mapping.json').write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'README.md').write_text(
        '# 合成盲审核对包\n\n仅把 reviewer 目录的副本交给评审；coordinator 保存映射及初始哈希，不能一起分发。'
        '\n\n目录分开不等于访问权限隔离。见过原样例的评审仍可能识别候选；文风差异也可能透露生成方式。'
        '本包只验证标签隐藏与审阅流程，不是已完成的盲评实验。真人审核0，真实模型调用0。\n', encoding='utf-8')
    return {'packets': len(projected), 'reviewer_files': len(hashes), 'human_reviewed': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.source, args.output)))


if __name__ == '__main__':
    main()
