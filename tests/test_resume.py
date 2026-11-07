"""Stage recovery and invalidation tests with local MP3s from FFmpeg only."""
import asyncio
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.stage_resume import StageCache, probe_audio, chapters_for_parts, verified_publish
from scripts import generate
from scripts.verify import check_episode


class CacheTests(unittest.TestCase):
    def test_reuse_success_and_regenerate_on_input_change(self):
        with tempfile.TemporaryDirectory() as d:
            stage = StageCache(d, '2026-11-07')
            calls = []
            def produce():
                calls.append(True)
                return {'segments': [{'speaker': 'NANA', 'text': '日本語の台本です。'}]}
            first, used = stage.json('part1', {'prompt': 'old', 'model': 'gemini-2.5'}, produce)
            self.assertFalse(used)
            second, used = StageCache(d, '2026-11-07').json(
                'part1', {'prompt': 'old', 'model': 'gemini-2.5'}, produce)
            self.assertTrue(used)
            self.assertEqual(first, second)
            self.assertEqual(len(calls), 1)
            _, used = stage.json('part1', {'prompt': 'new', 'model': 'gemini-2.5'}, produce)
            self.assertFalse(used)
            _, used = stage.json('part1', {'prompt': 'new', 'model': 'different-model'}, produce)
            self.assertFalse(used)
            self.assertEqual(len(calls), 3)

    def test_injected_failure_keeps_previous_stage(self):
        with tempfile.TemporaryDirectory() as d:
            stage = StageCache(d, '2026-11-07')
            a, used = stage.json('part1', {'prompt': 'x'}, lambda: {'ok': 1})
            with self.assertRaisesRegex(RuntimeError, 'injected failure'):
                stage.json('part2', {'prompt': 'y'}, lambda: (_ for _ in ()).throw(RuntimeError('injected failure')))
            recovered, used = StageCache(d, '2026-11-07').json('part1', {'prompt': 'x'},
                                                                lambda: (_ for _ in ()).throw(AssertionError('should reuse')))
            self.assertTrue(used)
            self.assertEqual(recovered, a)
            partial = list(Path(d).rglob('.partial-*.json'))
            self.assertEqual(partial, [])

    def test_cache_tampering_not_reused(self):
        with tempfile.TemporaryDirectory() as d:
            stage = StageCache(d, '2026-11-07')
            stage.json('feed', {'day': 1}, lambda: {'ok': True})
            path = next(Path(d).rglob('feed-*.json'))
            bad = json.loads(path.read_text())
            bad['value']['ok'] = False
            path.write_text(json.dumps(bad))
            x, used = stage.json('feed', {'day': 1}, lambda: {'ok': True})
            self.assertFalse(used)
            self.assertTrue(x['ok'])

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_tts_reuse_and_voice_or_text_invalidation(self):
        with tempfile.TemporaryDirectory() as d:
            stage = StageCache(d, '2026-11-07')
            count = []
            async def produce(path):
                count.append(True)
                subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                                '-f', 'lavfi', '-i', 'anullsrc=r=24000:cl=mono',
                                '-t', '1.0', '-c:a', 'libmp3lame', '-b:a', '64k', str(path)],
                               check=True)
            async def task():
                a, da, reuse = await stage.audio('クロードコード', 'ja-JP-NanamiNeural', '+0%', produce)
                self.assertFalse(reuse)
                b, db, reuse = await StageCache(d, '2026-11-07').audio(
                    'クロードコード', 'ja-JP-NanamiNeural', '+0%', produce)
                self.assertTrue(reuse)
                self.assertEqual(a, b)
                await stage.audio('クロードコード', 'ja-JP-KeitaNeural', '+0%', produce)
                await stage.audio('Claude Code', 'ja-JP-NanamiNeural', '+0%', produce)
                self.assertEqual(len(count), 3)
            asyncio.run(task())

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_published_pair_only_after_validation(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            audio = p / 'working.mp3'
            subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                            '-f', 'lavfi', '-i', 'anullsrc=r=24000:cl=mono',
                            '-t', '1', '-c:a', 'libmp3lame', '-b:a', '64k', str(audio)],
                           check=True)
            episode = p / 'episodes'; episode.mkdir()
            (episode / '2026-11-07.mp3').write_bytes(b'prior valid published bytes')
            (episode / '2026-11-07.json').write_text('old metadata')
            data = {'date': '2026-11-07', 'title': 'A new test', 'duration_seconds': round(probe_audio(audio)),
                    'audio': 'episodes/2026-11-07.mp3'}
            with self.assertRaisesRegex(RuntimeError, 'fail intentionally'):
                verified_publish(audio, data, episode, '2026-11-07',
                                 lambda *args, **kw: (_ for _ in ()).throw(RuntimeError('fail intentionally')))
            self.assertEqual((episode / '2026-11-07.json').read_text(), 'old metadata')
            self.assertEqual((episode / '2026-11-07.mp3').read_bytes(), b'prior valid published bytes')
            verified_publish(audio, data, episode, '2026-11-07', check_episode)
            self.assertEqual(json.loads((episode / '2026-11-07.json').read_text())['title'], 'A new test')

    def test_chapters_are_real_audio_based(self):
        points = chapters_for_parts([0, 2, 4], [10., 21., 31., 38., 40.], 140,
                                    ['ニュース', '深掘り', 'まとめ'])
        self.assertEqual(points[0]['start_seconds'], 0)
        self.assertAlmostEqual(points[1]['start_seconds'], 31, delta=1)
        self.assertAlmostEqual(points[2]['start_seconds'], 100, delta=1)


class FFmpegConcatIntegrationTests(unittest.TestCase):
    """Exercise the real render->concat->MP3 path with no API, network or TTS."""

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_two_short_segments_merge_and_resume_from_cache(self):
        calls = []
        class SilentTTS:
            def __init__(self, text, voice, rate):
                self.text = text
                self.voice = voice
                self.rate = rate

            async def save(self, path):
                calls.append(self.text)
                subprocess.run(
                    ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                     '-f', 'lavfi', '-i', 'anullsrc=r=24000:cl=mono',
                     '-t', '0.50', '-c:a', 'libmp3lame', '-b:a', '64k', str(path)],
                    check=True, timeout=30)

        segments = [
            {'speaker': 'NANA', 'text': '一つ目の検証用音声です。'},
            {'speaker': 'NANA', 'text': '二つ目の検証用音声です。'}
        ]
        with tempfile.TemporaryDirectory() as d, patch.object(
                generate.edge_tts, 'Communicate', SilentTTS):
            root = Path(d)
            work = root / 'work'
            work.mkdir()
            output, total, durations = asyncio.run(generate.render(segments, work))
            manifest = (work / 'concat.txt').read_text(encoding='utf-8')
            self.assertEqual(len(manifest.splitlines()), 2)
            self.assertTrue(all(line.startswith("file '") for line in manifest.splitlines()))
            self.assertNotIn(r'\n', manifest)
            self.assertGreater(total, 0)
            self.assertGreater(probe_audio(output), 0.75)
            self.assertEqual(len(durations), 2)
            self.assertEqual(len(calls), 2)

            stage = StageCache(root / 'cache', '2026-11-07')
            first, first_total, first_durations = asyncio.run(
                generate.render(segments, work, stage=stage))
            self.assertGreater(probe_audio(first), 0.75)
            self.assertEqual(len(calls), 4)
            second, second_total, second_durations = asyncio.run(
                generate.render(segments, work, stage=stage))
            self.assertEqual(first, second)
            self.assertEqual(first_total, second_total)
            self.assertEqual(first_durations, second_durations)
            self.assertEqual(len(calls), 4, 'Cached TTS segments must be reused')


if __name__ == '__main__':
    unittest.main()