import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, AsyncMock
from scripts import generate
from scripts import rebuild_request


class RebuildRequestTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.request = self.root / 'request.json'
        self.day = '2026-11-09'

    def write_request(self, **changes):
        self.request.write_text(json.dumps(dict(date=self.day, request_id='approved-test') | changes))

    def pending(self):
        return rebuild_request.pending(self.day, self.request, self.root)

    def test_absent_or_other_day_request_is_not_pending(self):
        self.assertFalse(self.pending())
        for day in ('2026-11-08', '2026-11-10'):
            self.write_request(date=day)
            self.assertFalse(self.pending())

    def test_pending_until_success_metadata_records_same_id_and_date(self):
        self.write_request()
        self.assertTrue(self.pending())
        episode = self.root / f'{self.day}.json'
        for value in ({'date': self.day}, {'date': self.day, 'rebuild_request_id': 'old'},
                      {'date': '2026-11-08', 'rebuild_request_id': 'approved-test'}):
            episode.write_text(json.dumps(value))
            self.assertTrue(self.pending())
        episode.write_text(json.dumps({'date': self.day, 'rebuild_request_id': 'approved-test'}))
        self.assertFalse(self.pending())
        self.assertFalse(self.pending(), 'Repeated queued checks must remain consumed')

    def test_invalid_episode_metadata_does_not_consume_request(self):
        self.write_request()
        for value in ('partial json', 'null', '[]'):
            (self.root / f'{self.day}.json').write_text(value)
            self.assertTrue(self.pending())

    def test_malformed_request_stops_instead_of_broadening_scope(self):
        for value in ('not json', 'null', '{}',
                      json.dumps({'date': '2026-11-40', 'request_id': 'test'}),
                      json.dumps({'date': self.day, 'request_id': '../all'}),
                      json.dumps({'date': self.day, 'request_id': 'test', 'force': True})):
            self.request.write_text(value)
            with self.assertRaises(ValueError):
                self.pending()

    def test_request_id_is_only_exposed_on_matching_day(self):
        self.write_request()
        self.assertEqual(rebuild_request.request_id(self.day, self.request), 'approved-test')
        self.assertIsNone(rebuild_request.request_id('2026-11-10', self.request))

    def test_generation_carries_request_id_into_verified_publish_only(self):
        episodes = self.root / 'episodes'
        episodes.mkdir()
        old_metadata = episodes / f'{self.day}.json'
        old_metadata.write_text('{"date":"2026-11-09","title":"previous"}')
        source = {'source': 'Test', 'title': 'Verified story', 'url': 'https://example.org/a'}
        result = ([{'speaker': 'NANA', 'text': '確認済みの記事の詳しい内容です。'}], {},
                  'topic', 'Verified news', [source], [0], ['ニュース'])
        audio = self.root / 'new.mp3'
        audio.write_bytes(b'new audio placeholder')
        with patch.object(generate, 'ROOT', self.root), \
             patch.object(generate, 'EP', episodes), \
             patch.object(generate, 'TODAY', self.day), \
             patch.object(generate, 'news', return_value=[source]), \
             patch.object(generate, 'write_script', return_value=result), \
             patch.object(generate, 'render', new=AsyncMock(return_value=(audio, 1, [1.0]))), \
             patch.object(generate.rebuild_request, 'request_id', return_value='approved-test'), \
             patch.object(generate.stage_resume, 'verified_publish', side_effect=RuntimeError('Validation failed')) as publish:
            with self.assertRaisesRegex(RuntimeError, 'Validation failed'):
                generate.main()
        self.assertEqual(publish.call_args.args[1]['rebuild_request_id'], 'approved-test')
        self.assertEqual(json.loads(old_metadata.read_text())['title'], 'previous')
        self.assertNotIn('rebuild_request_id', json.loads(old_metadata.read_text()))
