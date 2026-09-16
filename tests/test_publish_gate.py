"""Publication candidate scan controls; temporary git repositories only."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class PublishGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='yeoul-publish-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ('setup/pre-publish-check.sh', 'setup/check_markdown_links.py',
                     'bin/_pybin.sh'):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / name, target)
        (self.root / 'examples').mkdir()
        (self.root / 'examples/example.md').write_text('Synthetic worked example\n')
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        self.run_command(['git', 'init', '-q'])
        self.run_command(['git', 'add', '.'])

    def run_command(self, command):
        result = subprocess.run(command, cwd=self.root, env=self.env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def scan(self, expected):
        result = subprocess.run(['bash', 'setup/pre-publish-check.sh'], cwd=self.root,
                                env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout

    def test_new_candidate_is_scanned_before_staging(self):
        (self.root / 'new.md').write_text('\uac00', encoding='utf-8')
        self.assertIn('new.md', self.scan(1))

    def test_ignored_runtime_artifact_is_not_a_candidate(self):
        (self.root / '.gitignore').write_text('runtime.md\n')
        (self.root / 'runtime.md').write_text('\uac00', encoding='utf-8')
        self.scan(0)

    def test_localized_document_is_allowed(self):
        (self.root / 'README_KO.md').write_text('\uac00', encoding='utf-8')
        self.scan(0)

    def test_ui_localization_exemption_does_not_exempt_private_paths(self):
        path = self.root / 'mcp/yeoul_mcp/recovery_view.py'
        path.parent.mkdir(parents=True)
        path.write_text("label = '\uac00'\n", encoding='utf-8')
        self.scan(0)
        path.write_text("path = '" + '/' + "home/private/example'\n")
        self.assertIn('recovery_view.py', self.scan(1))

    def test_ui_localization_exemption_matches_source_archive_paths(self):
        path = self.root / 'mcp/yeoul_mcp/recovery_view.py'
        path.parent.mkdir(parents=True)
        path.write_text("label = '\uac00'\n", encoding='utf-8')
        shutil.rmtree(self.root / '.git')
        self.scan(0)

    def test_new_marketing_claim_is_not_ignored(self):
        (self.root / 'new.md').write_text('A revolutionary product\n')
        self.assertIn('over-claim copy found', self.scan(1))

    def test_existing_local_markdown_target_passes(self):
        (self.root / 'guide.md').write_text('[example](examples/example.md)\n')
        self.scan(0)

    def test_missing_and_escaping_markdown_targets_fail(self):
        for target, reason in (('missing.md', 'missing local target'),
                               ('../outside.md', 'link escapes repository')):
            with self.subTest(target=target):
                (self.root / 'guide.md').write_text(f'[bad]({target})\n')
                output = self.scan(1)
                self.assertIn(reason, output)

    def test_local_heading_anchors_and_duplicates(self):
        (self.root / 'target.md').write_text('# Local Heading\n\n## Repeat\n## Repeat\n')
        (self.root / 'guide.md').write_text(
            '[first](target.md#local-heading) [duplicate](target.md#repeat-1)\n')
        self.scan(0)
        (self.root / 'guide.md').write_text('[bad](target.md#missing-heading)\n')
        self.assertIn('missing local heading anchor', self.scan(1))

    def test_link_wrapping_an_image_is_also_checked(self):
        (self.root / 'badge.svg').write_text('<svg/>\n')
        (self.root / 'guide.md').write_text(
            '[![badge](badge.svg)](missing-destination.md)\n')
        self.assertIn('missing local target: missing-destination.md', self.scan(1))


if __name__ == '__main__':
    unittest.main()
