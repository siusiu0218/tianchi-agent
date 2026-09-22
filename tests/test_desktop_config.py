import tempfile
import unittest
from pathlib import Path

from desktop.config import read_settings, save_settings, load_model_settings


class ModelSettingsTests(unittest.TestCase):
    def test_restart_reads_registered_env_without_persisting_secret(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            env = root / '.env'
            env.write_text('LLM_BASE_URL=https://example.com/v1\nLLM_MODEL=test\nLLM_API_KEY=secret-test\n', encoding='utf-8')
            save_settings({'env_path': str(env)}, root)
            settings, key = load_model_settings(read_settings(root), environ={})
            self.assertEqual(settings['base_url'], 'https://example.com/v1')
            self.assertEqual(settings['model'], 'test')
            self.assertEqual(key, 'secret-test')
            self.assertNotIn('secret-test', (root / 'settings.json').read_text())
            env.write_text('LLM_MODEL=changed\nLLM_API_KEY=new-secret\n', encoding='utf-8')
            settings, key = load_model_settings(read_settings(root), environ={})
            self.assertEqual(settings['model'], 'changed')
            self.assertEqual(key, 'new-secret')

    def test_environment_overrides_file_and_missing_file_is_safe(self):
        settings, key = load_model_settings({'env_path': 'missing-file.env', 'model': 'saved'},
                                            environ={'LLM_MODEL': 'override', 'LLM_API_KEY': 'runtime'})
        self.assertEqual(settings['model'], 'override')
        self.assertEqual(key, 'runtime')
