"""Offline reliability tests: no Gemini key, Edge TTS, or network needed."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests
from scripts import generate, verify


class AudioDurationTests(unittest.TestCase):
    def test_short_valid_episode_is_not_discarded(self):
        with patch.object(generate.subprocess, 'run') as run:
            self.assertEqual(generate.fit_duration(Path('/tmp/test.mp3'), 550), 550)
            run.assert_not_called()

    def test_zero_duration_is_not_treated_as_success(self):
        with self.assertRaises(RuntimeError):
            generate.fit_duration(Path('/tmp/test.mp3'), 0)

    def test_22_minute_episode_is_adjusted_without_cutting_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / 'test.mp3'
            audio.write_bytes(b'original')
            adjusted = audio.with_name('test.adjusted.mp3')
            def fake_run(command, **kwargs):
                if command[0] == 'ffmpeg':
                    self.assertIn('atempo=', ' '.join(command))
                    adjusted.write_bytes(b'adjusted audio')
                    return SimpleNamespace(returncode=0)
                return SimpleNamespace(stdout='1190.0\n', returncode=0)
            with patch.object(generate.subprocess, 'run', side_effect=fake_run):
                self.assertEqual(generate.fit_duration(audio, 1318), 1190)
            self.assertEqual(audio.read_bytes(), b'adjusted audio')
            self.assertFalse(adjusted.exists())

    def test_very_long_episode_is_published_without_extreme_speedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / 'test.mp3'
            audio.write_bytes(b'original')
            adjusted = audio.with_name('test.adjusted.mp3')
            def fake_run(command, **kwargs):
                if command[0] == 'ffmpeg':
                    self.assertIn('atempo=1.25000', command)
                    adjusted.write_bytes(b'adjusted')
                    return SimpleNamespace(returncode=0)
                return SimpleNamespace(stdout='1520.0\n', returncode=0)
            with patch.object(generate.subprocess, 'run', side_effect=fake_run):
                self.assertEqual(generate.fit_duration(audio, 1900), 1520)


class GeminiRetryTests(unittest.TestCase):
    def test_connection_timeout_is_retried(self):
        response = SimpleNamespace(raise_for_status=lambda: None,
                                   json=lambda: {'candidates': []})
        with patch.object(generate.requests, 'post',
                          side_effect=[requests.Timeout(), response]) as post, \
             patch.object(generate.time, 'sleep'):
            data = generate.request_gemini('test', 'not-a-real-key', 'test-model')
        self.assertEqual(data, {'candidates': []})
        self.assertEqual(post.call_count, 2)

    def test_bad_api_key_is_not_retried(self):
        response = requests.Response()
        response.status_code = 403
        response._content = b'permission denied'
        response.url = 'https://example.invalid/'
        with patch.object(generate.requests, 'post', return_value=response) as post, \
             patch.object(generate.time, 'sleep'):
            with self.assertRaises(requests.HTTPError):
                generate.request_gemini('test', 'not-a-real-key', 'test-model')
        self.assertEqual(post.call_count, 1)


class EpisodeVerificationTests(unittest.TestCase):
    def make_episode(self, root, day='2026-11-01'):
        (root / f'{day}.mp3').write_bytes(b'FAKE' * 2048)
        data = {'date': day, 'title': 'Offline test', 'duration_seconds': 987,
                'audio': f'episodes/{day}.mp3'}
        (root / f'{day}.json').write_text(json.dumps(data), encoding='utf-8')
        return data

    def test_valid_episode_and_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = self.make_episode(root)
            (root / 'index.json').write_text(json.dumps([d]), encoding='utf-8')
            self.assertEqual(verify.check_episode('2026-11-01', base=root), d)
            verify.check_archive(base=root)

    def test_missing_audio_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_episode(root)
            (root / '2026-11-01.mp3').unlink()
            with self.assertRaises(RuntimeError):
                verify.check_episode('2026-11-01', base=root)

    def test_archive_duration_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = self.make_episode(root)
            (root / 'index.json').write_text(
                json.dumps([{**d, 'duration_seconds': 500}]), encoding='utf-8')
            with self.assertRaises(ValueError):
                verify.check_archive(base=root)


if __name__ == '__main__':
    unittest.main()
