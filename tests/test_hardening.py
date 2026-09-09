"""Adversarial contract tests. Every write/record/agent stub is in a temporary workspace."""
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'bin'))
from prereg_check import bind, claim, resolve, read_verified
from verify_core import verify, canonical, eligible


def ledger(path, rows, width=64):
    previous = 'genesis'
    output = []
    for row in rows:
        body = {k: v for k, v in row.items() if k not in ('seal', 'sig')}
        body['prev_seal'] = previous
        seal = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False,
                                         allow_nan=False).encode()).hexdigest()[:width]
        output.append(dict(body, seal=seal))
        previous = seal
    path.write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in output), encoding='utf-8')
    return output


class Hardening(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='yeoul contract ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = dict(os.environ, YEOUL_PROJECTS=str(self.root/'projects'),
                        YEOUL_INDEX=str(self.root/'index.md'), AM_LEDGER=str(self.root/'actions.jsonl'),
                        YEOUL_LEDGER=str(self.root/'claims.jsonl'), PYTHONDONTWRITEBYTECODE='1')
        self.claims = self.root/'claims.jsonl'
        self.row = dict(claim_id='c1', metric='m', kill_condition='effect size d < 0.2 over 3 seeds')
        self.arc = self.root/'arc'
        self.arc.mkdir()
        self.todo = self.root/'TODO.md'

    def call(self, script, *args, env=None):
        return subprocess.run(['bash', str(REPO/'bin'/script), *map(str, args)],
                              cwd=self.root, env=env or self.env, capture_output=True,
                              text=True, encoding='utf-8', timeout=30)

    def prereg(self):
        ledger(self.claims, [self.row])
        bind(self.arc, 'c1', self.claims)

    def opened(self):
        result = self.call('arc-open', 'audit', '--arcs-dir='+str(self.root/'arcs'))
        self.assertEqual(result.returncode, 0, result.stderr)
        return next((self.root/'arcs').glob('*_audit'))

    def test_unsealed_ledger_refused(self):
        self.claims.write_text(json.dumps(self.row))
        with self.assertRaises(ValueError):
            bind(self.arc, 'c1', self.claims)
        self.assertFalse((self.arc/'.prereg').exists())

    def test_tampered_and_malformed_ledgers_refused(self):
        ledger(self.claims, [self.row])
        original = self.claims.read_text()
        for bad in ['', original.replace('0.2', '0.9'), original+'{bad', '[]',
                    original.replace('"metric": "m"', '"metric": "m", "metric": "n"')]:
            with self.subTest(data=bad[:35]):
                self.claims.write_text(bad)
                with self.assertRaises(ValueError):
                    read_verified(self.claims)

    def test_bad_later_entry_invalidates_whole_chain(self):
        ledger(self.claims, [self.row, dict(claim_id='c2', kill_condition='stop')])
        self.claims.write_text(self.claims.read_text().replace('"stop"', '"changed"'))
        with self.assertRaises(ValueError):
            claim(self.claims, 'c1')

    def test_first_write_cannot_be_repaired_by_duplicate(self):
        ledger(self.claims, [dict(claim_id='c1', metric='m'), self.row])
        with self.assertRaises(ValueError):
            claim(self.claims, 'c1')

    def test_legacy_hash_and_threshold_registration(self):
        rows = ledger(self.claims, [dict(claim_id='c1', kill_threshold={'min': 0.2})], width=16)
        bind(self.arc, 'c1', self.claims)
        binding, condition = resolve(self.arc)
        self.assertEqual(binding['seal'], rows[0]['seal'])
        self.assertEqual(json.loads(condition), {'min': 0.2})

    def test_modified_pinned_registration_even_rehashed_is_refused(self):
        self.prereg()
        ledger(self.claims, [dict(self.row, kill_condition='new threshold')])
        with self.assertRaises(ValueError):
            resolve(self.arc)

    def test_appended_valid_records_preserve_pin(self):
        self.prereg()
        ledger(self.claims, [self.row, dict(claim_id='c2', kill_condition='other bar')])
        self.assertEqual(resolve(self.arc)[0]['claim_id'], 'c1')

    def test_link_removal_and_rebinding_refused(self):
        self.prereg()
        (self.arc/'.prereg').unlink()
        with self.assertRaises(ValueError):
            resolve(self.arc)
        other = self.root/'other.jsonl'
        ledger(other, [dict(self.row, claim_id='c2')])
        with self.assertRaises(ValueError):
            bind(self.arc, 'c2', other)

    def test_legacy_link_needs_explicit_verified_upgrade(self):
        ledger(self.claims, [self.row])
        (self.arc/'.prereg').write_text(f'c1\n{self.claims}\n')
        with self.assertRaises(ValueError):
            resolve(self.arc)
        bind(self.arc, 'c1', self.claims)
        self.assertEqual(resolve(self.arc)[0]['claim_id'], 'c1')

    def test_command_replacement_and_item_deletion_blocked_before_execution(self):
        baseline = '- [ ] real requirement. verify: `false`\n'
        for changed in ['- [x] real requirement. verify: `touch injected`\n', '',
                        '- [x] different requirement. verify: `true`\n']:
            with self.subTest(changed=changed):
                self.todo.write_text(changed)
                self.assertEqual(verify(self.todo, baseline=baseline, revert=True, require=True), 3)
                self.assertEqual(self.todo.read_text(), baseline)
        self.assertFalse((self.root/'injected').exists())

    def test_true_and_false_verifications(self):
        baseline = '- [ ] honest. verify: `true`\n- [ ] broken. verify: `false`\n'
        self.todo.write_text(baseline.replace('[ ]', '[x]'))
        self.assertEqual(verify(self.todo, baseline=baseline, revert=True, require=True), 1)
        self.assertIn('[x] honest', self.todo.read_text())
        self.assertIn('[ ] broken', self.todo.read_text())

    def test_missing_baseline_fails_closed_and_never_runs(self):
        self.todo.write_text('- [x] unsafe. verify: `touch injected`\n')
        self.assertEqual(self.call('verify-gate', self.todo).returncode, 3)
        self.assertFalse((self.root/'injected').exists())

    def test_baseline_creation_is_explicit_and_non_overwriting(self):
        self.todo.write_text('- [ ] honest. verify: `true`\n')
        self.assertEqual(self.call('verify-baseline', self.todo).returncode, 0)
        self.assertEqual(self.call('verify-baseline', self.todo).returncode, 3)
        self.todo.write_text(self.todo.read_text().replace('[ ]', '[x]'))
        self.assertEqual(self.call('verify-gate', self.todo).returncode, 0)

    def test_verify_timeout(self):
        baseline = '- [x] bounded. verify: `sleep 5`\n'
        self.todo.write_text(baseline)
        self.assertEqual(verify(self.todo, baseline=baseline, timeout=0.05, revert=True), 1)
        self.assertIn('[ ] bounded', self.todo.read_text())

    def test_malformed_and_empty_todos_are_ineligible(self):
        for text in ['', '# no items', '- [x] absent', '- [ ] missing. verify:',
                     '- [ ] empty. verify: ``', '- [X] hidden\n- [ ] ok. verify: `true`']:
            with self.subTest(text=text):
                self.assertFalse(eligible(text))

    def test_draft_refusal_and_final_archive_states(self):
        arc = self.opened()
        self.assertEqual(self.call('arc-close', arc, 'GO audit').returncode, 0)
        thread = arc/'ARC'/(arc.name+'.md')
        self.assertIn('status: "Close-Pending"', thread.read_text())
        self.assertEqual(self.call('arc-close', arc, 'GO audit').returncode, 4)
        self.assertNotIn('status: "Closed"', thread.read_text())
        summary = next(arc.glob('_SUMMARY*'))
        summary.write_text(summary.read_text().replace('(fill in)', 'concrete conclusion'))
        self.assertEqual(self.call('arc-close', arc, 'GO audit').returncode, 0)
        archived = arc.parent/'_archive'/arc.name
        self.assertIn('status: "Closed"', (archived/'ARC'/thread.name).read_text())
        self.assertIn('ARCHIVE_RECORD ', (archived/'STATE.md').read_text())

    def test_deleting_required_kill_fields_is_not_a_pass(self):
        arc = self.opened()
        self.call('arc-close', arc, 'KILL audit')
        summary = next(arc.glob('_SUMMARY*'))
        text = summary.read_text().replace('(fill in)', 'concrete conclusion')
        summary.write_text('\n'.join(line for line in text.splitlines() if '(unfilled)' not in line))
        self.assertEqual(self.call('arc-close', arc, 'KILL audit').returncode, 5)
        self.assertTrue(arc.exists())

    def test_archive_collision_is_not_overwritten(self):
        arc = self.opened()
        self.call('arc-close', arc, 'GO audit')
        summary = next(arc.glob('_SUMMARY*'))
        summary.write_text(summary.read_text().replace('(fill in)', 'concrete conclusion'))
        archived = arc.parent/'_archive'/arc.name
        archived.mkdir(parents=True)
        self.assertEqual(self.call('arc-close', arc, 'GO audit').returncode, 9)
        self.assertTrue(arc.exists())

    def fake_loop(self, body, *extra):
        dev = self.root/'projects'/'p'/'dev'
        dev.mkdir(parents=True)
        todo = dev/'TODO.md'
        todo.write_text('- [ ] real task. verify: `true`\n')
        fake = self.root/'fake agent.py'
        fake.write_text('import os,json\nfrom pathlib import Path\np=Path(os.environ["AUDIT_TODO"])\n'+body)
        env = dict(self.env, AUDIT_TODO=str(todo))
        result = self.call('ralph', 'p', '--agent-cmd='+shlex.join([sys.executable, str(fake)]), *extra, env=env)
        return result, todo

    def test_ralph_refuses_worker_criterion_changes(self):
        result, todo = self.fake_loop('p.write_text("- [x] changed. verify: `true`\\n")\nprint(json.dumps({"usage":{"input_tokens":1,"output_tokens":1}}))\n')
        self.assertEqual(result.returncode, 3, result.stdout+result.stderr)
        self.assertIn('[ ] real task', todo.read_text())

    def test_ralph_one_round_means_one_invocation(self):
        result, todo = self.fake_loop('print(json.dumps({"usage":{"input_tokens":1,"output_tokens":1}}))\n', '--max-rounds=1')
        self.assertEqual(result.returncode, 2, result.stdout+result.stderr)
        self.assertEqual(len(list((todo.parent/'ralph_log').glob('round_*.json'))), 1)

    def test_ralph_missing_usage_is_not_zero(self):
        result, _ = self.fake_loop('print("{}")\n')
        self.assertEqual(result.returncode, 2)
        self.assertIn('STOP:unmeasured', result.stdout)

    def test_ralph_success_and_quoted_agent_path(self):
        result, _ = self.fake_loop('p.write_text(p.read_text().replace("[ ]","[x]"))\nprint(json.dumps({"usage":{"input_tokens":1,"output_tokens":1}}))\n', '--max-rounds=1')
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('RALPH_DONE', result.stdout)

    def test_ralph_round_timeout(self):
        result, _ = self.fake_loop('import time\ntime.sleep(5)\n', '--round-timeout=0.05')
        self.assertEqual(result.returncode, 124, result.stdout+result.stderr)

    def test_loop_guard_boundary_and_invalid_counts(self):
        self.call('loop-guard', self.arc, 'init', '--max-rounds=1')
        self.assertIn('STOP:max-rounds', self.call('loop-guard', self.arc, 'tick', '--tokens=0').stdout)
        self.assertNotEqual(self.call('loop-guard', self.arc, 'tick', '--tokens=-1').returncode, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
