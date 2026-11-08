"""Offline story evidence and event dedup tests; no external requests."""
import unittest
from unittest.mock import Mock
from scripts.story_quality import (normalize_url, group_stories, same_story,
                                   ArticleFetcher, collect_evidence, public_sources,
                                   select_excerpts, MAX_EXCERPT_CHARS, MAX_EXCERPTS)


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


    def enrich_markup(self, markup, **fields):
        session = Mock()
        session.get.side_effect = [FakeResponse('User-agent: *\nAllow: /'), FakeResponse(markup)]
        return ArticleFetcher(session).enrich(dict(self.stories()[0], **fields))

    def test_complete_qualifications_and_late_attribution_are_preserved(self):
        metric = ('The report examines the full development workflow. ' * 6 +
                  'Review-stage dwell time increased 441% compared with the baseline; '
                  'this is elapsed waiting time, not active reviewer working time.')
        paragraphs = ['An introduction to the current audio and engineering landscape.']
        paragraphs += ['Background context without specific claims about the product.'] * 6
        paragraphs += [metric, 'Phonon was developed by Gradium and published on Hugging Face.',
                       'The model supports English and French; other languages are not evaluated.',
                       'The license permits research only; commercial use requires permission.']
        result = self.enrich_markup('<article>' + ''.join('<p>' + p + '</p>' for p in paragraphs) + '</article>')
        self.assertIn(metric, result['facts'])
        self.assertIn(paragraphs[-3], result['facts'])
        self.assertIn(paragraphs[-2], result['facts'])
        self.assertIn(paragraphs[-1], result['facts'])
        self.assertEqual(result['facts'], [x['text'] for x in result['evidence_excerpts']])
        self.assertLessEqual(sum(map(len, result['facts'])), MAX_EXCERPT_CHARS)
        self.assertLessEqual(len(result['facts']), MAX_EXCERPTS)

    def test_excerpts_skip_oversized_paragraph_without_cutting(self):
        long = 'This entire paragraph is too long. ' * MAX_EXCERPT_CHARS
        short = 'Review dwell time rose 441%, not reviewer working time.'
        excerpts = select_excerpts([long, short], 'https://example.com/article')
        self.assertEqual([x['text'] for x in excerpts], [short])
        self.assertEqual(excerpts, select_excerpts([long, short], 'https://example.com/article?utm_source=rss'))
        self.assertNotEqual(excerpts[0]['id'], select_excerpts([short + ' Changed.'], 'https://example.com/article')[0]['id'])

    def test_publication_date_is_not_feed_or_updated_date(self):
        markup = ('<meta property="article:published_time" content="2026-11-06T23:30:00-08:00">'
                  '<meta property="article:modified_time" content="2026-11-07T12:00:00Z">'
                  '<article><p>' + 'Verified text describing the study and its limitations. ' * 5 + '</p></article>')
        result = self.enrich_markup(markup, date='2026-11-07')
        self.assertEqual(result['date'], '2026-11-07')
        self.assertEqual(result['article_published_date'], '2026-11-06')
        public = public_sources([dict(result, supporting_sources=[result])])[0]
        self.assertNotIn('facts', public)
        self.assertNotIn('evidence_excerpts', public)
        self.assertNotIn('facts', public['supporting_sources'][0])
        self.assertNotIn('evidence_excerpts', public['supporting_sources'][0])

    def test_jsonld_article_date_only_and_conflicts_abstain(self):
        body = '<article><p>' + 'A complete paragraph describing verified article evidence. ' * 5 + '</p></article>'
        structured = '<script type="application/ld+json">{"@graph":[{"@type":"BlogPosting","url":"https://blog.google/ai/gemini-live-new-voice","datePublished":"2026-11-06","dateModified":"2026-11-07"}]}</script>'
        self.assertEqual(self.enrich_markup(structured + body)['article_published_date'], '2026-11-06')
        conflict = '<meta property="article:published_time" content="2026-11-05">'
        self.assertEqual(self.enrich_markup(conflict + structured + body)['article_published_date'], '')
        modified = '<script type="application/ld+json">{"@type":"Article","dateModified":"2026-11-07"}</script>'
        self.assertEqual(self.enrich_markup(modified + body)['article_published_date'], '')

    def test_related_article_dates_are_not_current_article_metadata(self):
        body = '<article><p>' + 'A complete paragraph describing article evidence. ' * 6 + '</p></article>'
        unrelated = '<script type="application/ld+json">{"@type":"Article","url":"https://example.org/another-article","datePublished":"2026-11-07"}</script>'
        unscoped = '<meta itemprop="datePublished" content="2026-11-07"><time itemprop="datePublished" datetime="2026-11-07"></time>'
        self.assertEqual(self.enrich_markup(unrelated + unscoped + body)['article_published_date'], '')
        page_meta = '<meta property="article:published_time" content="2026-11-06">'
        self.assertEqual(self.enrich_markup(unrelated + page_meta + body)['article_published_date'], '2026-11-06')

    def test_rejects_private_or_insecure_host(self):
        session = Mock()
        fetcher = ArticleFetcher(session)
        self.assertFalse(fetcher.allowed('http://example.com/article'))
        self.assertFalse(fetcher.allowed('https://127.0.0.1/internal'))
        self.assertFalse(fetcher.allowed('https://169.254.169.254/metadata'))
        session.get.assert_not_called()


if __name__ == '__main__':
    unittest.main()