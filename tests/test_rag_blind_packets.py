from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.blind_rag_review_packets import export, project, render
from scripts.export_rag_review_packet import packets


class BlindPacketTests(unittest.TestCase):
    def source(self, root, data=None):
        root.mkdir()
        hashes = {}
        data = packets() if data is None else data
        for packet in data:
            path = root / (packet['id'] + '.json')
            path.write_text(json.dumps(packet, ensure_ascii=False), encoding='utf-8')
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        (root / 'manifest.json').write_text(json.dumps({'packets': len(data), 'initial_file_sha256': hashes}))

    def test_projection_omits_labels_and_preserves_evidence(self):
        for packet in packets():
            before = deepcopy(packet)
            public = project(packet, 'R001')
            text = json.dumps(public) + render(public)
            for label in (packet['id'], packet['preview_id'], 'auto_approved', 'model_claims', 'missing_p0_followup'):
                self.assertNotIn(label, text)
            self.assertEqual(public['evidence']['case'], packet['snapshot']['case_snapshot'])
            self.assertEqual([r['text'] for r in public['candidate']],
                             [r['text'] for r in packet['sentence_reviews']])
            self.assertEqual(packet, before)
            self.assertEqual(public['human_review']['status'], 'unreviewed')

    def test_mapping_separate_complete_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.source(root / 'source')
            result = export(root / 'source', root / 'out')
            self.assertEqual(result['packets'], 8)
            key = json.loads((root / 'out/coordinator/mapping.json').read_text())
            self.assertEqual(len({r['source_id'] for r in key['mapping']}), 8)
            self.assertEqual(len(list((root / 'out/reviewer').iterdir())), 16)
            before = {p: p.read_bytes() for p in (root / 'out').rglob('*') if p.is_file()}
            with self.assertRaises(FileExistsError):
                export(root / 'source', root / 'out')
            self.assertTrue(all(p.read_bytes() == raw for p, raw in before.items()))

    def test_tampered_source_refused_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.source(root / 'source')
            next((root / 'source').glob('SYN*.json')).write_text('{}')
            with self.assertRaises(ValueError):
                export(root / 'source', root / 'out')
            self.assertFalse((root / 'out').exists())

    def test_unequal_evidence_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = packets()
            data[0]['snapshot']['case_snapshot']['tickets'] = [{'工单号': 'different'}]
            self.source(root / 'source', data)
            with self.assertRaises(ValueError):
                export(root / 'source', root / 'out')
            self.assertFalse((root / 'out').exists())


if __name__ == '__main__':
    unittest.main()
