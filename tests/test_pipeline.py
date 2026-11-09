from editorial_fixtures import draft, response, report_draft, SOURCE
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




class SoloHostTests(unittest.TestCase):
    def test_only_one_female_voice_at_normal_rate(self):
        self.assertEqual(generate.VOICES, {'NANA': 'ja-JP-NanamiNeural'})
        self.assertEqual(generate.TTS_RATE, '+0%')

    def test_valid_solo_segments(self):
        segments = [{'speaker': 'NANA', 'text': '今日はAIの話題を紹介しますね。'}
                    for _ in range(6)]
        self.assertEqual(generate.validate_segments(segments), segments)

    def test_other_dj_is_rejected(self):
        segments = [{'speaker': 'NANA', 'text': '今日のニュースです。'}
                    for _ in range(6)]
        segments[1] = {'speaker': 'MASU', 'text': '司会は交代しましょうか。'}
        with self.assertRaisesRegex(ValueError, 'Invalid solo DJ'):
            generate.validate_segments(segments)

    def test_script_generation_prompts_single_host(self):
        prompts = []
        def fake_gemini(prompt, key, model, **kwargs):
            prompts.append(prompt)
            if prompt.startswith('EDITORIAL AUDIT'):
                return response({'approved': True, 'issues': []})
            payload = report_draft()
            if len(prompts) == 1:
                payload['episode_title'] = '一人で楽しく語るAIニュース'
            return response(payload)
        with patch.dict(generate.os.environ, {'GEMINI_API_KEY': 'test-key'}), \
             patch.object(generate, 'episode_history', return_value=[]), \
             patch.object(generate.story_quality, 'collect_evidence', return_value=[SOURCE]), \
             patch.object(generate, 'request_gemini', side_effect=fake_gemini):
            segments, usage, focus, title, featured, starts, labels = generate.write_script([])
        self.assertEqual(len(prompts), 2)
        self.assertIn('This chapter role: report', prompts[0])
        self.assertIn('Exactly ONE Japanese female host NANA', prompts[0])
        self.assertTrue(prompts[1].startswith('EDITORIAL AUDIT'))
        self.assertTrue(all(x['speaker'] == 'NANA' for x in segments))
        self.assertEqual(len(segments), 4)
        self.assertEqual(len(starts), len(labels))
        self.assertEqual(title, '一人で楽しく語るAIニュース')
        self.assertEqual(usage['api_calls'], 2)


class TTSPronunciationTests(unittest.TestCase):
    def test_claude_code_variants_have_correct_reading(self):
        for spelling in ('Claude Code', 'ClaudeCode', 'Claude-Code', 'claude code',
                         'Claude・Code', 'クローダーコード'):
            with self.subTest(spelling=spelling):
                self.assertEqual(generate.tts_text(spelling), 'クロードコード')

    def test_preserves_original_script_and_other_names(self):
        original = 'Claude CodeとCodex、GitHubを比較します。'
        self.assertEqual(generate.tts_text(original), 'クロードコードとCodex、GitHubを比較します。')
        self.assertEqual(original, 'Claude CodeとCodex、GitHubを比較します。')

    def test_does_not_rewrite_other_words(self):
        self.assertEqual(generate.tts_text('Claude models and Claude Codec'),
                         'Claude models and Claude Codec')

    def test_japanese_context(self):
        self.assertEqual(generate.tts_text('最新のClaude Code。ClaudeCodeも同じです。'),
                         '最新のクロードコード。クロードコードも同じです。')



class GeminiOutputBudgetTests(unittest.TestCase):
    def test_flash_has_explicit_thinking_limit(self):
        response = SimpleNamespace(raise_for_status=lambda: None,
                                   json=lambda: {'candidates': []})
        with patch.object(generate.requests, 'post', return_value=response) as post:
            generate.request_gemini('script prompt', 'test-key', 'gemini-2.5-flash')
        config = post.call_args.kwargs['json']['generationConfig']
        self.assertEqual(config['thinkingConfig']['thinkingBudget'], 512)
        self.assertEqual(config['maxOutputTokens'], 8192)

    def test_retry_can_disable_thinking_and_raise_output_budget(self):
        response = SimpleNamespace(raise_for_status=lambda: None,
                                   json=lambda: {'candidates': []})
        with patch.object(generate.requests, 'post', return_value=response) as post:
            generate.request_gemini('script prompt', 'test-key', 'gemini-2.5-flash',
                                    thinking_budget=0, max_output_tokens=12288)
        config = post.call_args.kwargs['json']['generationConfig']
        self.assertEqual(config['thinkingConfig'], {'thinkingBudget': 0})
        self.assertEqual(config['maxOutputTokens'], 12288)

    def test_other_models_do_not_receive_gemini_25_thinking_config(self):
        response = SimpleNamespace(raise_for_status=lambda: None,
                                   json=lambda: {'candidates': []})
        with patch.object(generate.requests, 'post', return_value=response) as post:
            generate.request_gemini('script prompt', 'test-key', 'other-model')
        config = post.call_args.kwargs['json']['generationConfig']
        self.assertNotIn('thinkingConfig', config)

    def test_max_tokens_recovers_on_second_attempt(self):
        budgets = []
        def fake_gemini(prompt, key, model, **kwargs):
            budgets.append(kwargs['thinking_budget'])
            if not prompt.startswith('EDITORIAL AUDIT'):
                self.assertIn('This chapter role: report', prompt)
            if len(budgets) == 1:
                return {'usageMetadata': {}, 'candidates': [{
                    'finishReason': 'MAX_TOKENS',
                    'content': {'parts': [{'text': '{"segments":['}]}
                }]}
            if prompt.startswith('EDITORIAL AUDIT'):
                return response({'approved': True, 'issues': []})
            return response(report_draft())
        with patch.dict(generate.os.environ, {'GEMINI_API_KEY': 'test-key'}), \
             patch.object(generate, 'episode_history', return_value=[]), \
             patch.object(generate.story_quality, 'collect_evidence', return_value=[SOURCE]), \
             patch.object(generate, 'request_gemini', side_effect=fake_gemini), \
             patch.object(generate.time, 'sleep'):
            segments, usage, focus, title, featured, starts, labels = generate.write_script([])
        self.assertEqual(budgets, [512, 0, 512])
        self.assertEqual(len(segments), 4)
        self.assertEqual(len(starts), 1)
        self.assertEqual(usage['api_calls'], 3)

if __name__ == '__main__':
    unittest.main()
