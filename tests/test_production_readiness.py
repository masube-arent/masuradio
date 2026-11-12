"""Production diagnosis without authentication, network, synthesis or real audio."""
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import production_readiness as gate, work_script
from test_work_script import DAY, submission


class DateTests(unittest.TestCase):
    def test_jst_today_including_midnight_boundary(self):
        now = dt.datetime(2026, 11, 11, 15, tzinfo=dt.timezone.utc)
        self.assertEqual(gate.resolve_date(now=now), '2026-11-12')
        self.assertEqual(gate.resolve_date(now=now-dt.timedelta(seconds=1)), '2026-11-11')

    def test_exact_seven_dates_allowed(self):
        now = dt.datetime(2026, 11, 12, 3, tzinfo=dt.timezone.utc)
        for age in range(7):
            day = (now.date()-dt.timedelta(days=age)).isoformat()
            self.assertEqual(gate.resolve_date(day, now), day)
        for day in ('2026-11-13', '2026-11-05', '2020-01-01', '2026-02-30',
                    '20261112', '2026-1-12', '2026-11-12\n', ' 2026-11-12', '../escape', '２０２６-１１-１２'):
            with self.subTest(day=day), self.assertRaises(ValueError):
                gate.resolve_date(day, now)


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.probe = patch.object(gate.verify, 'check_episode', side_effect=RuntimeError('absent')).start()
        self.addCleanup(patch.stopall)

    def diagnose(self, replacement=False):
        return gate.diagnose(self.root, DAY, replacement)

    def test_missing_script_and_review_fail(self):
        status, detail = self.diagnose()
        self.assertEqual(status, 'missing_input')
        self.assertIn('script.json, review.json', detail)
        folder = submission(self.root)
        (folder/'review.json').unlink()
        self.assertEqual(self.diagnose()[0], 'missing_input')
        (folder/'review.json').write_text('{}')
        (folder/'script.json').unlink()
        self.assertEqual(self.diagnose()[0], 'missing_input')

    def test_ready_exact_hash_is_reported(self):
        folder = submission(self.root)
        status, detail = self.diagnose()
        self.assertEqual(status, 'ready')
        self.assertIn(work_script.digest(json.loads((folder/'script.json').read_text())), detail)
        self.assertIn('not confirmation of publication', detail)

    def test_changed_evidence_requires_new_review(self):
        folder = submission(self.root)
        data = json.loads((folder/'script.json').read_text())
        data['chapters'][0]['sources'][0]['evidence_excerpts'][0]['text'] += ' Additional evidence.'
        (folder/'script.json').write_text(json.dumps(data))
        status, detail = self.diagnose()
        self.assertEqual(status, 'invalid_input')
        self.assertIn('stale', detail)

    def test_rejected_malformed_and_incomplete_reviews_fail(self):
        folder = submission(self.root)
        original = json.loads((folder/'review.json').read_text())
        for value in ('broken JSON', 'null', json.dumps(original | {'decision': 'rejected'}),
                      json.dumps(original | {'checks': []}), json.dumps(original | {'reviewer': 'writer'})):
            with self.subTest(value=value):
                (folder/'review.json').write_text(value)
                self.assertEqual(self.diagnose()[0], 'invalid_input')

    def test_valid_existing_pair_needs_no_draft(self):
        self.probe.side_effect = None
        with patch.object(work_script, 'load_submission') as load:
            self.assertEqual(self.diagnose()[0], 'already_published')
            load.assert_not_called()
        self.probe.assert_called_with(DAY, base=self.root/'episodes', probe=True)

    def test_explicit_replacement_needs_review_even_when_published(self):
        self.probe.side_effect = None
        self.assertEqual(self.diagnose(True)[0], 'missing_input')
        self.probe.assert_not_called()
        submission(self.root)
        self.assertEqual(self.diagnose(True)[0], 'ready')

    def test_reviewed_rebuild_request_is_date_scoped_and_consumed(self):
        self.probe.side_effect = None
        (self.root/'.github').mkdir()
        request = self.root/'.github/rebuild-request.json'
        request.write_text(json.dumps({'date': DAY, 'request_id': 'approved-test'}))
        self.assertEqual(self.diagnose()[0], 'missing_input')
        (self.root/'episodes').mkdir()
        (self.root/'episodes'/f'{DAY}.json').write_text(json.dumps({'date': DAY, 'rebuild_request_id': 'approved-test'}))
        self.assertEqual(self.diagnose()[0], 'already_published')
        request.write_text(json.dumps({'date': '2026-11-09', 'request_id': 'other-day'}))
        self.assertEqual(self.diagnose()[0], 'already_published')
        request.write_text('broken')
        self.assertEqual(self.diagnose()[0], 'invalid_request')

    def test_cli_failure_has_summary_and_no_ready_output(self):
        summary, output = self.root/'summary', self.root/'output'
        with patch.object(gate, 'ROOT', self.root), patch.object(gate.subprocess, 'check_output', return_value='abc123\n'), \
             patch('sys.argv', ['readiness', '--date', DAY]), \
             patch.dict(os.environ, GITHUB_STEP_SUMMARY=str(summary), GITHUB_OUTPUT=str(output)):
            self.assertEqual(gate.main(), 1)
        self.assertFalse(output.exists())
        text = summary.read_text()
        self.assertIn(DAY, text)
        self.assertIn('abc123', text)
        self.assertIn('missing_input', text)
        self.assertIn('merge to main', text)

    def test_stale_review_cli_is_fatal(self):
        folder = submission(self.root)
        review = json.loads((folder/'review.json').read_text())
        review['script_sha256'] = '0' * 64
        (folder/'review.json').write_text(json.dumps(review))
        output = self.root/'output'
        with patch.object(gate, 'ROOT', self.root), patch.object(gate.subprocess, 'check_output', return_value='abc123\n'), \
             patch('sys.argv', ['readiness', '--date', DAY]), patch.dict(os.environ, GITHUB_OUTPUT=str(output)):
            self.assertEqual(gate.main(), 1)
        self.assertFalse(output.exists())

    def test_invalid_date_cli_is_fatal_and_summarized(self):
        summary, output = self.root/'summary', self.root/'output'
        with patch.object(gate.subprocess, 'check_output', return_value='abc123\n'), \
             patch('sys.argv', ['readiness', '--resolve-date', '--date', '9999-12-31']), \
             patch.dict(os.environ, GITHUB_STEP_SUMMARY=str(summary), GITHUB_OUTPUT=str(output)):
            self.assertEqual(gate.main(), 1)
        self.assertFalse(output.exists())
        self.assertIn('invalid_date', summary.read_text())
        self.probe.assert_not_called()

    def test_success_cli_output_preserves_existing_skip_contract(self):
        for published in (False, True):
            if not published:
                submission(self.root)
            self.probe.side_effect = None if published else RuntimeError('absent')
            output = self.root/f'output-{published}'
            with patch.object(gate, 'ROOT', self.root), patch.object(gate.subprocess, 'check_output', return_value='abc123\n'), \
                 patch('sys.argv', ['readiness', '--date', DAY]), patch.dict(os.environ, GITHUB_OUTPUT=str(output)):
                self.assertEqual(gate.main(), 0)
            self.assertEqual(output.read_text(), f'ready={str(published).lower()}\n')
