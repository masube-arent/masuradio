"""Exercise the workflow's explicit replacement gate without API or audio calls."""
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


class ReplacementWorkflowTests(unittest.TestCase):
    def run_gate(self, replace, valid, requested=False):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/daily.yml').read_text()
        section = workflow.split("      - name: Check whether today's episode already exists\n", 1)[1]
        script = textwrap.dedent(section.split('        run: |\n', 1)[1].split('\n      - name:', 1)[0])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fake = root / 'python'
            fake.write_text('#!/bin/sh\nif [ \"$1\" = \"scripts/rebuild_request.py\" ]; then echo ' + ('true' if requested else 'false') + '; exit 0; fi\necho checked >> \"$CHECK_LOG\"\nexit ' + ('0' if valid else '1') + '\n')
            fake.chmod(0o755)
            output, log = root / 'output', root / 'checks'
            env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'],
                       REPLACE_EXISTING=replace, GITHUB_OUTPUT=str(output), CHECK_LOG=str(log))
            subprocess.run(['bash', '-e', '-c', script], env=env, check=True, capture_output=True)
            return output.read_text().strip(), log.exists()

    def test_valid_episode_is_skipped_without_explicit_replacement(self):
        for value in ('false', ''):
            self.assertEqual(self.run_gate(value, True), ('ready=true', True))

    def test_missing_episode_generates_normally(self):
        self.assertEqual(self.run_gate('false', False), ('ready=false', True))

    def test_only_explicit_replacement_bypasses_valid_episode_skip(self):
        self.assertEqual(self.run_gate('true', True), ('ready=false', False))

    def test_input_defaults_off_and_is_manual_only(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/daily.yml').read_text()
        self.assertIn('default: false', workflow)
        self.assertIn("github.event_name == 'workflow_dispatch' && inputs.replace_existing", workflow)

    def test_pending_pr_request_rebuilds_once_without_manual_dispatch(self):
        self.assertEqual(self.run_gate('false', True, requested=True), ('ready=false', False))
        self.assertEqual(self.run_gate('false', True, requested=False), ('ready=true', True))
