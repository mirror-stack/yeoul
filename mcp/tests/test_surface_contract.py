"""CLI/MCP decisions and Mirror result interoperability. No production writes."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'mcp'))
sys.path.insert(0, str(ROOT/'bin'))
sys.path.insert(0, str(ROOT/'tests'))
from yeoul_mcp import server
from prereg_check import bind, read_verified
from test_hardening import ledger


class Surface(unittest.TestCase):
    def test_cli_mcp_eligibility_and_nondefault_projects_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            projects = root/'custom-projects'
            dev = projects/'p'/'dev'
            dev.mkdir(parents=True)
            for content, expected in [('', 3), ('- [x] no command\n', 3),
                                      ('- [ ] malformed. verify:\n', 3),
                                      ('- [ ] good. verify: `true`\n', 0)]:
                with self.subTest(content=content), patch.dict(os.environ, {'YEOUL_PROJECTS':str(projects)}):
                    (dev/'TODO.md').write_text(content)
                    result = server.ralph_gate_check('p', workspace=tmp)
                    self.assertEqual(result['exit_code'], expected, result)
                    self.assertFalse((dev/'ralph_log').exists(), 'dry check must not create loop state')

    def test_mcp_missing_usage_is_unmeasured(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(server.loop_guard_init(tmp)['exit_code'], 0)
            result = server.loop_guard_tick(tmp)
            self.assertIn('STOP:unmeasured', result['stdout'])

    def test_result_adapter_matches_mirror_publish_contract(self):
        from mirror_stack_mcp.gate import decide
        from mirror_stack_mcp.integrity import read_verified as mirror_verified
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arc = root/'arc'
            arc.mkdir()
            claims = root/'claims.jsonl'
            row = dict(claim_id='c1', metric='m', kill_condition='effect size d < 0.2 over 3 seeds')
            ledger(claims, [row])
            bind(arc, 'c1', claims)
            self.assertEqual(read_verified(claims), mirror_verified(claims)[0])
            summary = root/'result.md'
            summary.write_text('Measured d = 0.05; preregistered effect was not observed.')
            for status in ('pass', 'fail', 'inconclusive'):
                with self.subTest(status=status):
                    actions = root/(status+'.jsonl')
                    result = subprocess.run([sys.executable, str(ROOT/'bin'/'result_record.py'), str(arc),
                                             '--status', status, '--summary-file', str(summary),
                                             '--am-ledger', str(actions)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                    self.assertFalse(json.loads(result.stdout)['published'])
                    entry = read_verified(actions)[0]
                    self.assertEqual(entry['action'], 'result')
                    self.assertEqual(entry['payload']['status'], status)
                    self.assertEqual(decide(claims, 'c1', gate='publish', am_ledger=actions)['decision'], 'GO')

    def test_action_close_is_not_a_measurement_result(self):
        from actmirror import am
        from mirror_stack_mcp.gate import decide
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claims, actions = root/'claims.jsonl', root/'actions.jsonl'
            ledger(claims, [dict(claim_id='c1', kill_condition='stop at the preregistered bar')])
            am.record(str(actions), agent='test', action='arc-close', target='c1')
            self.assertEqual(decide(claims, 'c1', gate='publish', am_ledger=actions)['decision'], 'BLOCK')


if __name__ == '__main__':
    unittest.main(verbosity=2)
