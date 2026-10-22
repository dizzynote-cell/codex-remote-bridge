import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from desktop_projects import DesktopProjects


class DesktopProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state.json'
        self.data = {'local-projects': {
            'p1': {'name': 'Language', 'rootPaths': ['C:/old']},
            'p2': {'name': 'PC cleanup', 'rootPaths': ['D:/new', 'C:/old']}},
            'project-order': ['p2', 'p1'],
            'thread-project-assignments': {'t': {'projectKind': 'local', 'projectId': 'p2'}},
            'projectless-thread-ids': ['solo']}
        self.save()
        self.resolver = DesktopProjects(self.path)

    def save(self):
        self.path.write_text(json.dumps(self.data), encoding='utf-8')

    def test_assignment_beats_old_cwd_without_changing_execution_directory(self):
        result = self.resolver.enrich({'id': 't', 'cwd': 'C:/old'})
        self.assertEqual(result['desktopProject']['name'], 'PC cleanup')
        self.assertEqual(result['desktopProject']['rootPaths'], ['D:/new', 'C:/old'])
        self.assertEqual(result['cwd'], 'C:/old')
        self.assertEqual([p['id'] for p in self.resolver.snapshot()['projects']], ['p2', 'p1'])

    def test_client_move_is_detected_without_restarting(self):
        self.assertEqual(self.resolver.enrich({'id': 't'})['desktopProject']['id'], 'p2')
        self.data['thread-project-assignments']['t']['projectId'] = 'p1'
        self.data['local-projects']['p1']['name'] = 'Renamed language project'
        self.save()
        self.assertEqual(self.resolver.enrich({'id': 't'})['desktopProject']['name'], 'Renamed language project')

    def test_projectless_is_explicit_and_unknown_has_no_assignment(self):
        self.assertEqual(self.resolver.enrich({'id': 'solo', 'cwd': 'C:/old'})['desktopProject']['kind'], 'projectless')
        self.assertIsNone(self.resolver.enrich({'id': 'unknown'})['desktopProject'])

    def test_partial_state_write_keeps_last_good_snapshot(self):
        before = self.resolver.snapshot()
        self.path.write_text('{', encoding='utf-8')
        self.assertEqual(self.resolver.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
