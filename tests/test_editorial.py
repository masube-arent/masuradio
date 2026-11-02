"""Topic diversity and source deduplication tests (network-free)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import datetime as dt

from scripts import generate


class EditorialTests(unittest.TestCase):
    def test_seven_distinct_weekday_pillars(self):
        self.assertEqual(len(generate.SHOWS), 7)
        self.assertEqual(len({s[0] for s in generate.SHOWS}), 7)
        self.assertTrue(any('音声' in s[0] for s in generate.SHOWS))
        self.assertTrue(any('仕事術' in s[0] for s in generate.SHOWS))

    def test_sources_are_balanced_across_publishers(self):
        items = [
            {'source': source, 'title': f'{source} workflow {n}', 'summary': 'automation example',
             'date': '2026-11-02', 'url': f'https://example.org/{source}/{n}'}
            for source in ('Codex', 'OpenAI', 'DeepMind', 'GitHub', 'Hugging Face')
            for n in range(4)
        ]
        selected = generate.select_sources(items, 'workflow', [])
        self.assertEqual(len(selected), 8)
        self.assertGreaterEqual(len({x['source'] for x in selected}), 4)
        self.assertLessEqual(max(sum(x['source'] == s for x in selected)
                                 for s in ('Codex', 'OpenAI', 'DeepMind', 'GitHub',
                                           'Hugging Face')), 2)

    def test_recently_featured_stories_get_deprioritized(self):
        items = [
            {'source': 'Codex', 'title': 'workflow old', 'summary': '',
             'date': '2026-11-03', 'url': 'https://example.org/old'},
            {'source': 'OpenAI', 'title': 'workflow new', 'summary': '',
             'date': '2026-11-02', 'url': 'https://example.org/new'},
        ]
        history = [{'used_urls': ['https://example.org/old']}]
        selected = generate.select_sources(items, 'workflow', history, limit=1)
        self.assertEqual(selected[0]['url'], 'https://example.org/new')

    def test_old_history_uses_first_three_sources_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / '2026-11-02.json'
            p.write_text(json.dumps({
                'date': '2026-11-02', 'title': 'Yesterday show',
                'sources': [{'url': f'https://example.org/{x}'} for x in range(8)]
            }), encoding='utf-8')
            history = generate.episode_history(Path(tmp))
        self.assertEqual(history[0]['title'], 'Yesterday show')
        self.assertEqual(len(history[0]['used_urls']), 3)

    def test_prerelease_chatter_is_filtered(self):
        now=dt.datetime.now(dt.timezone.utc)
        stamp=now.utctimetuple()
        entries = [
            {'title': title, 'link': f'https://example.org/{i}',
             'published_parsed': stamp, 'summary': ''}
            for i,title in enumerate(['0.167.0-alpha.3','0.167.0-beta.1','0.166.0'])
        ]
        with patch.object(generate.requests, 'get', return_value=SimpleNamespace(
                raise_for_status=lambda: None, content=b'fake')), \
             patch.object(generate.feedparser, 'parse',
                          return_value=SimpleNamespace(entries=entries)):
            news = generate.read_feed('Codex','https://example.org/')
        self.assertEqual([x['title'] for x in news], ['0.166.0'])


if __name__ == '__main__':
    unittest.main()
