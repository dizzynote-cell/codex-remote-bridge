"""Distribution checks; do not open user config or start the bridge."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DistributionTests(unittest.TestCase):
    def test_version_markers_agree(self):
        version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
        self.assertIn('v' + version, (ROOT / 'README.md').read_text(encoding='utf-8'))
        self.assertIn('## v' + version, (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8'))

    def test_cloud_paths_and_callback_are_configurable(self):
        source = (ROOT / 'cloud/app.py').read_text(encoding='utf-8')
        self.assertIn("os.environ['PUBLIC_BASE_URL']", source)
        self.assertIn("callback=PUBLIC_BASE_URL+", source)
        client = (ROOT / 'cloud/web/app.js').read_text(encoding='utf-8')
        self.assertIn('runtimeConfig.standaloneDir', client)
        self.assertIn('runtimeConfig.projectsRoot', client)
        self.assertNotIn('Plus 预计续费', client)

    def test_cloud_history_imports_without_local_app_on_path(self):
        result = subprocess.run([sys.executable, '-I', '-c',
            'import sys; sys.path.insert(0,sys.argv[1]); import history_store, thread_payload',
            str(ROOT/'cloud')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((ROOT/'app/thread_payload.py').read_text(encoding='utf-8'),
                         (ROOT/'cloud/thread_payload.py').read_text(encoding='utf-8'))

    def test_local_web_assets_are_present_and_shared(self):
        for folder in ['web', 'cloud/web']:
            root = ROOT / folder
            html = (root / 'index.html').read_text(encoding='utf-8')
            for path in re.findall(r'(?:src|href)="(/[^"?#]+)', html):
                self.assertTrue((root / path.lstrip('/')).is_file(), (folder, path))
        for name in ['turn-health.js', 'turn-health.css', 'markdown.js', 'markdown.css',
                     'lib/markdown-it-15.0.3.min.js', 'lib/markdown-it.LICENSE.txt']:
            self.assertEqual((ROOT/'web'/name).read_text(encoding='utf-8'),
                             (ROOT/'cloud/web'/name).read_text(encoding='utf-8'), name)


if __name__ == '__main__':
    unittest.main()
