"""Offline story evidence and event dedup tests; no external requests."""
import unittest
from unittest.mock import Mock
from scripts.story_quality import (normalize_url, group_stories, same_story,
                                   ArticleFetcher, collect_evidence, public_sources)


class FakeResponse:
    def __init__(self, body='', *, status=200, headers=None):
        self.status_code = status
        self.headers = headers or {'Content-Type': 'text/html'}
        self.encoding = 'utf-8'
        self.text = body
        self.body = body.encode('utf-8')
        self.closed = False

    def iter_content(self, chunk_size=8192):
        for i in range(0, len(self.body), chunk_size):
            yield self.body[i:i + chunk_size]

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ValueError(f'HTTP {self.status_code}')

    def close(self):
        self.closed = True


class QualityTests(unittest.TestCase):
    def test_tracking_params_and_fragment_not_identity(self):
        a = 'https://NEWS.example.com/post?p=2&utm_medium=email&utm_source=hi#part3'
        b = 'https://news.example.com/post?utm_campaign=example&p=2'
        self.assertEqual(normalize_url(a), normalize_url(b))
        self.assertNotEqual(normalize_url(a), normalize_url('https://news.example.com/post?p=3'))

    def test_semantic_query_ids_remain_distinct(self):
        a = {'source':'Example', 'url':'https://example.com/story?id=1',
             'title':'New feature announced', 'date':'2026-11-03'}
        b = dict(a, url='https://example.com/story?id=2')
        self.assertFalse(same_story(a,b))

    def stories(self):
        return [
            {'source': 'Google AI', 'url': 'https://blog.google/ai/gemini-live-new-voice?utm_source=rss',
             'title': 'Google introduces Gemini Live new voice assistant on Android',
             'date': '2026-11-03'},
            {'source': 'DeepMind', 'url': 'https://deepmind.google/blog/gemini-live-new-voice',
             'title': 'Google launches Gemini Live new voice assistant for Android',
             'date': '2026-11-04'},
            {'source': 'Google AI', 'url': 'https://blog.google/ai/gemini-live-pricing',
             'title': 'Google announces Gemini Live new pricing tiers for businesses',
             'date': '2026-11-04'},
        ]

    def test_cross_publisher_same_event_keeps_secondary_source(self):
        result = group_stories(self.stories())
        self.assertEqual(len(result), 2)
        first = result[0]
        self.assertEqual(len(first['supporting_sources']), 1)
        self.assertNotEqual(first['url'], first['supporting_sources'][0]['url'])

    def test_same_product_different_announcement_not_collapsed(self):
        a, _, b = self.stories()
        self.assertFalse(same_story(a, b))

    def test_same_url_even_if_tracker_changes(self):
        a = self.stories()[0]
        b = dict(a, url=a['url'] + '&fbclid=xyz')
        self.assertEqual(len(group_stories([a, b])), 1)

    def test_failed_fetch_does_not_authorize_deep_dive(self):
        session = Mock()
        session.get.return_value = FakeResponse(status=403)
        fetcher = ArticleFetcher(session=session)
        entry = dict(self.stories()[0])
        result = fetcher.enrich(entry)
        self.assertEqual(result['evidence_status'], 'summary_only')
        self.assertEqual(result['facts'], [])

    def test_robots_disallow_respected(self):
        session = Mock()
        session.get.return_value = FakeResponse('User-agent: *\nDisallow: /')
        result = ArticleFetcher(session).enrich(self.stories()[0])
        self.assertEqual(result['evidence_status'], 'summary_only')
        self.assertEqual(session.get.call_count, 1, 'article should not be fetched')

    def test_article_body_extract_and_public_redaction(self):
        article = '<html><body><article>' + ''.join(
            '<p>Gemini Live new voice assistant provides several practical ' +
            f' capabilities and examples for Android users in paragraph {i}. </p>'
            for i in range(6)) + '</article></body></html>'
        session = Mock()
        session.get.side_effect = [FakeResponse('User-agent: *\nAllow: /'), FakeResponse(article)]
        result = ArticleFetcher(session).enrich(self.stories()[0])
        self.assertEqual(result['evidence_status'], 'body')
        self.assertGreater(len(result['facts']), 0)
        public = public_sources([result])[0]
        self.assertNotIn('facts', public)
        self.assertEqual(public['evidence_status'], 'body')
        self.assertIn('url', public)

    def test_bounded_shortlist_never_attempts_every_article(self):
        calls = []
        class Fetcher:
            def enrich(self, item):
                calls.append(item)
                return dict(item, evidence_status='body', facts=['verified'])
        inputs = [dict(self.stories()[0], url=f'https://example.com/{n}') for n in range(9)]
        result = collect_evidence(inputs, Fetcher(), max_articles=3)
        self.assertEqual(len(calls), 3)
        self.assertEqual(result[-1]['evidence_status'], 'summary_only')

    def test_sitewide_paragraphs_not_evidence_without_article_section(self):
        body = '<html><body>' + '<p>' + ('Advertisement and site navigation. '*15) + '</p></body></html>'
        session = Mock()
        session.get.side_effect = [FakeResponse('User-agent: *\nAllow: /'), FakeResponse(body)]
        result = ArticleFetcher(session).enrich(self.stories()[0])
        self.assertEqual(result['evidence_status'], 'summary_only')

    def test_rejects_private_or_insecure_host(self):
        session = Mock()
        fetcher = ArticleFetcher(session)
        self.assertFalse(fetcher.allowed('http://example.com/article'))
        self.assertFalse(fetcher.allowed('https://127.0.0.1/internal'))
        self.assertFalse(fetcher.allowed('https://169.254.169.254/metadata'))
        session.get.assert_not_called()


if __name__ == '__main__':
    unittest.main()