"""Bounded live-delivery checks with in-memory HTTP responses only."""
import io
from http.client import IncompleteRead
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.request import Request

from scripts import verify_live


class Response(io.BytesIO):
    status = 200


class Opener:
    def __init__(self, data, failures=0):
        self.data, self.failures, self.calls = data, failures, []

    def open(self, req, timeout):
        self.calls.append(req.full_url)
        if self.failures:
            self.failures -= 1
            raise OSError('temporary transport failure')
        name = req.full_url.rsplit('/', 1)[-1]
        return Response(self.data[name])


class LiveDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        day = '2026-11-12'
        meta = {'date': day, 'title': 'Fixture', 'duration_seconds': 123,
                'audio': f'episodes/{day}.mp3'}
        self.data = {'index.json': json.dumps([meta]).encode(),
                     f'{day}.json': json.dumps(meta).encode(),
                     f'{day}.mp3': b'FAKE' * 2048}
        for name, content in self.data.items():
            (self.root / name).write_bytes(content)

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, data=None, **kwargs):
        return verify_live.check_live('https://example.github.io/radio/', self.root,
                                      opener=Opener(data or self.data), retry_delay=0, **kwargs)

    def test_exact_archive_and_audio_bytes_pass(self):
        result = self.check()
        self.assertEqual(result['latest_date'], '2026-11-12')
        self.assertEqual(result['verified_files'], 3)

    def test_same_size_wrong_audio_is_rejected(self):
        wrong = dict(self.data, **{'2026-11-12.mp3': b'EVIL' * 2048})
        with self.assertRaisesRegex(RuntimeError, 'do not regenerate audio'):
            self.check(wrong, attempts=1)

    def test_stale_index_is_rejected(self):
        wrong = dict(self.data, **{'index.json': b'[]'})
        with self.assertRaises(RuntimeError):
            self.check(wrong, attempts=1)

    def test_changed_script_metadata_is_rejected(self):
        wrong = dict(self.data, **{'2026-11-12.json': b'{}'})
        with self.assertRaises(RuntimeError):
            self.check(wrong, attempts=1)

    def test_oversized_body_is_bounded(self):
        wrong = dict(self.data, **{'index.json': b'x' * 100000})
        with self.assertRaises(RuntimeError):
            self.check(wrong, attempts=1)

    def test_transient_failure_retries_read_only(self):
        opener = Opener(self.data, failures=1)
        with patch.object(verify_live.time, 'sleep') as sleep:
            result = verify_live.check_live('https://example.github.io/radio/', self.root,
                                            opener=opener, retry_delay=1)
        self.assertEqual(result['episodes'], 1)
        sleep.assert_called_once_with(1)
        self.assertEqual(len(opener.calls), 4)

    def test_truncated_http_response_uses_retry_budget(self):
        opener = Opener(self.data)
        original_open = opener.open
        calls = []
        def truncated_once(req, timeout):
            calls.append(req.full_url)
            if len(calls) == 1:
                raise IncompleteRead(b'partial response')
            return original_open(req, timeout)
        opener.open = truncated_once
        with patch.object(verify_live.time, 'sleep') as sleep:
            result = verify_live.check_live('https://example.github.io/radio/', self.root,
                                            opener=opener, retry_delay=1)
        self.assertEqual(result['episodes'], 1)
        sleep.assert_called_once_with(1)
        self.assertEqual(len(calls), 4)

    def test_retries_are_bounded(self):
        opener = Opener(self.data, failures=100)
        with self.assertRaises(RuntimeError), patch.object(verify_live.time, 'sleep'):
            verify_live.check_live('https://example.github.io/radio/', self.root,
                                   opener=opener, attempts=2)
        self.assertEqual(len(opener.calls), 2)

    def test_bad_base_url_rejected_before_http(self):
        for base in ('http://example.com/', 'https://user:secret@example.com/',
                     'https://127.0.0.1/', 'https://example.local/',
                     'https://example.com/?token=secret', 'https://example.com/#secret'):
            with self.subTest(base=base), self.assertRaises(ValueError):
                verify_live.checked_base_url(base)

    def test_foreign_redirect_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'changed origin'):
            verify_live.SameOriginRedirect().redirect_request(
                Request('https://example.github.io/radio/'), None, 302, 'redirect', {},
                'http://internal.local/data')

    def test_invalid_local_archive_prevents_http(self):
        (self.root / '2026-11-12.mp3').unlink()
        opener = Opener(self.data)
        with self.assertRaises(RuntimeError):
            verify_live.check_live('https://example.github.io/radio/', self.root, opener=opener)
        self.assertEqual(opener.calls, [])

    def test_pages_verifies_after_deployment_without_new_permissions(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/pages.yml').read_text()
        self.assertLess(workflow.index('uses: actions/deploy-pages@v4'), workflow.index('python scripts/verify_live.py'))
        self.assertNotIn('actions: write', workflow)

    def test_validation_supersedes_stale_runs_per_pr(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/validate.yml').read_text()
        self.assertIn('github.event.pull_request.number || github.ref', workflow)
        self.assertIn('cancel-in-progress: true', workflow)
        self.assertIn('timeout-minutes: 15', workflow)
