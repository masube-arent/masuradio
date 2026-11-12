"""Same-script rebuild requests consume once without replacing valid audio."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import publish_work, rebuild_request, stage_resume, verify, work_script
from test_work_script import DAY, package, submission


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class WorkRebuildRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        submission(self.root)
        self.episodes = self.root / 'episodes'
        self.episodes.mkdir()
        self.audio = self.episodes / f'{DAY}.mp3'
        self.metadata = self.episodes / f'{DAY}.json'
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                        '-f', 'lavfi', '-i', 'anullsrc=r=24000:cl=mono', '-t', '1',
                        '-c:a', 'libmp3lame', '-b:a', '64k', str(self.audio)], check=True)
        self.old = {'date': DAY, 'title': 'Reviewed broadcast',
                    'audio': f'episodes/{DAY}.mp3',
                    'duration_seconds': stage_resume.probe_audio(self.audio),
                    'script_hash': work_script.digest(package())}
        self.metadata.write_text(json.dumps(self.old), encoding='utf-8')
        self.original_json = self.metadata.read_bytes()
        self.original_audio = self.audio.read_bytes()
        self.request = self.root / '.github/rebuild-request.json'
        self.request.parent.mkdir()
        self.request.write_text(json.dumps({'date': DAY, 'request_id': 'recovery-2'}))
        self.render = self.enterContext(patch.object(
            publish_work.generate, 'render', side_effect=AssertionError('TTS called')))

    def pending(self):
        return rebuild_request.pending(DAY, self.request, self.episodes)

    def assert_original(self):
        self.assertEqual(self.metadata.read_bytes(), self.original_json)
        self.assertEqual(self.audio.read_bytes(), self.original_audio)
        self.assertTrue(self.pending())
        self.render.assert_not_called()
        self.assertEqual(list(self.episodes.glob('.radio-review-*')), [])

    def test_consumes_once_after_real_pair_validation_without_tts(self):
        self.assertTrue(self.pending())
        with patch.object(verify, 'check_episode', wraps=verify.check_episode) as check:
            result = publish_work.publish(self.root, DAY, replace_existing=True)
        self.assertEqual(check.call_count, 2)
        self.assertTrue(all(call.kwargs['probe'] for call in check.call_args_list))
        self.assertEqual(result, dict(self.old, rebuild_request_id='recovery-2'))
        self.assertEqual(self.audio.read_bytes(), self.original_audio)
        self.assertFalse(self.pending())
        saved_json = self.metadata.read_bytes()
        with patch.object(publish_work.os, 'replace', side_effect=AssertionError('rewrite')):
            self.assertEqual(publish_work.publish(self.root, DAY), result)
        self.assertEqual(self.metadata.read_bytes(), saved_json)
        self.render.assert_not_called()

    def test_staging_write_failure_preserves_pair(self):
        with patch.object(stage_resume, 'atomic_json', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                publish_work.publish(self.root, DAY, replace_existing=True)
        self.assert_original()

    def test_staged_validation_failure_preserves_pair(self):
        original = verify.check_episode
        def check(day, base, probe):
            if base != self.episodes:
                raise RuntimeError('staged pair rejected')
            return original(day, base, probe)
        with patch.object(verify, 'check_episode', side_effect=check):
            with self.assertRaisesRegex(RuntimeError, 'staged pair rejected'):
                publish_work.publish(self.root, DAY, replace_existing=True)
        self.assert_original()

    def test_atomic_replace_failure_preserves_pair(self):
        original = publish_work.os.replace
        def replace(source, target):
            if Path(target) == self.metadata:
                raise OSError('replace failed')
            return original(source, target)
        with patch.object(publish_work.os, 'replace', side_effect=replace):
            with self.assertRaisesRegex(OSError, 'replace failed'):
                publish_work.publish(self.root, DAY, replace_existing=True)
        self.assert_original()

    def test_different_script_still_requires_explicit_replacement(self):
        self.old['script_hash'] = 'different-script'
        self.metadata.write_text(json.dumps(self.old))
        self.original_json = self.metadata.read_bytes()
        with self.assertRaisesRegex(ValueError, 'explicit replacement'):
            publish_work.publish(self.root, DAY)
        self.assert_original()

    def test_failed_review_does_not_consume_request(self):
        (self.root / 'drafts' / DAY / 'review.json').unlink()
        with self.assertRaises(FileNotFoundError):
            publish_work.publish(self.root, DAY, replace_existing=True)
        self.assert_original()

    def test_invalid_existing_audio_does_not_consume_request(self):
        self.audio.write_bytes(b'corrupt')
        self.original_audio = self.audio.read_bytes()
        with self.assertRaisesRegex(AssertionError, 'TTS called'):
            publish_work.publish(self.root, DAY, replace_existing=True)
        self.assertEqual(self.metadata.read_bytes(), self.original_json)
        self.assertEqual(self.audio.read_bytes(), self.original_audio)
        self.assertTrue(self.pending())


if __name__ == '__main__':
    unittest.main()
