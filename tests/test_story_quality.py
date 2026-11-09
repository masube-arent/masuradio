"""Offline evidence acquisition regressions. Never calls the network or an AI."""
import unittest
from unittest.mock import Mock

import requests

from scripts.story_quality import (
    ArticleFetcher, MAX_BYTES, MAX_ROBOTS_BYTES, MAX_EXCERPT_CHARS,
    _bounded_get, _safe_public_https, EvidenceFetchError,
)


BODY = ('The release adds a setting to select a smaller preview model for the current '
        'session. The setting is available only on supported desktop clients; '
        'older clients retain their previous behavior. The publisher recommends '
        'checking the active model before using the setting on an important task.')
URL = 'https://example.com/article'
RELEASE_URL = 'https://github.com/anthropics/claude-code/releases/tag/v2.1.319'


class Response:
    def __init__(self, body='', status=200, headers=None):
        self.body = body.encode()
        self.status_code = status
        self.headers = headers or {'Content-Type': 'text/html; charset=utf-8'}
        self.encoding = 'utf-8'
        self.closed = False

    def iter_content(self, chunk_size=8192):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start:start + chunk_size]

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError('Do not publish this arbitrary message', response=self)

    def close(self):
        self.closed = True


def robots(body='User-agent: *\nAllow: /'):
    return Response(body, headers={'Content-Type': 'text/plain'})


class EvidenceAcquisitionTests(unittest.TestCase):
    def enrich(self, markup, url=URL):
        session = Mock()
        session.get.side_effect = [robots(), Response(markup)]
        return ArticleFetcher(session).enrich({'url': url, 'title': 'Release'})

    def test_complete_release_list_with_heading_and_nested_qualifications(self):
        markup = ('<main><h1>Site menu</h1><ul><li>' + BODY + '</li></ul>'
                  '<div class="markdown-body my-3"><h2>Preview limitations</h2>'
                  '<p>All changes below apply only to Windows preview builds.</p>'
                  '<ul><li>Added a model selection setting.<ul><li>' + BODY + '</li>'
                  '<li>Not supported in older clients.</li></ul></li></ul></div>'
                  '<p>Site-wide promotion that should not become release evidence.</p></main>')
        result = self.enrich(markup, RELEASE_URL)
        self.assertEqual(result['evidence_status'], 'body')
        joined = '\n'.join(result['facts'])
        self.assertNotIn('Site menu', joined)
        self.assertNotIn('Site-wide promotion', joined)
        list_excerpt = next(x for x in result['facts'] if 'Added a model' in x)
        self.assertTrue(list_excerpt.startswith('Preview limitations\n'))
        self.assertIn('All changes below apply only to Windows preview builds.', list_excerpt)
        self.assertIn(BODY, list_excerpt)
        self.assertTrue(list_excerpt.endswith('Not supported in older clients.'))
        self.assertEqual(joined.count(BODY), 1, 'nested paragraphs/items must not become duplicates')

    def test_release_without_markdown_body_cannot_use_main_ui(self):
        result = self.enrich('<main><p>' + BODY + '</p><ul><li>' + BODY + '</li></ul></main>', RELEASE_URL)
        self.assertEqual(result['fetch_reason'], 'insufficient_article_text')

    def test_large_release_list_selects_whole_items_with_context_within_budget(self):
        items = [f'Fix {number}: ' + BODY for number in range(34)]
        markup = ('<main><div class="markdown-body"><h2>Experimental client fixes</h2>'
                  '<p>These changes apply only to Windows preview builds.</p><ul>' +
                  ''.join('<li>' + item + '</li>' for item in items) + '</ul></div></main>')
        self.assertGreater(len(markup), MAX_EXCERPT_CHARS)
        result = self.enrich(markup, RELEASE_URL)
        self.assertEqual(result['evidence_status'], 'body')
        excerpts = [text for text in result['facts'] if 'Fix ' in text]
        self.assertGreater(len(excerpts), 1)
        for excerpt in excerpts:
            self.assertTrue(excerpt.startswith('Experimental client fixes\n'
                                              'These changes apply only to Windows preview builds.\n'))
            self.assertIn(excerpt.split('\n')[-1], items)
        self.assertLessEqual(sum(map(len, result['facts'])), MAX_EXCERPT_CHARS)

    def test_main_navigation_lists_are_not_article_body(self):
        result = self.enrich('<main><ul><li>' + BODY + '</li></ul></main>')
        self.assertEqual(result['evidence_status'], 'summary_only')

    def test_explicit_article_excludes_surrounding_main_promotions(self):
        result = self.enrich('<main><p>' + BODY.replace('setting', 'promotion') + '</p>'
                             '<article><p>' + BODY + '</p></article><p>' +
                             BODY.replace('setting', 'cookie notice') + '</p></main>')
        self.assertEqual(result['facts'], [BODY])

    def test_article_list_retains_parent_heading_and_preamble(self):
        result = self.enrich('<article><h1>Desktop preview</h1><h2>Limitations</h2>'
                             '<p>These options are experimental and may be removed.</p>'
                             '<ol><li>' + BODY + '</li><li>Use only with a backup.</li></ol></article>')
        self.assertEqual(result['evidence_status'], 'body')
        self.assertIn('Desktop preview\nLimitations\nThese options are experimental and may be removed.\n' +
                      BODY + ' Use only with a backup.', result['facts'])

    def test_sibling_headings_do_not_leak_into_later_section(self):
        result = self.enrich('<article><h1>Release notes</h1><h2>Preview features</h2><p>' + BODY + '</p>'
                             '<h2>Stable fixes</h2><p>' + BODY.replace('setting', 'fix') + '</p></article>')
        self.assertEqual(len(result['facts']), 2)
        self.assertTrue(result['facts'][1].startswith('Release notes\nStable fixes\n'))
        self.assertNotIn('Preview features', result['facts'][1])

    def test_closed_article_heading_does_not_leak_into_sibling_article(self):
        second = BODY.replace('setting', 'other setting')
        result = self.enrich('<main><article><h2>CLI only</h2><p>' + BODY + '</p></article>'
                             '<article><p>' + second + '</p></article></main>')
        self.assertEqual(result['facts'], ['CLI only\n' + BODY, second])

    def test_closed_section_heading_and_preamble_do_not_leak_into_following_body(self):
        second = BODY.replace('setting', 'stable feature')
        result = self.enrich('<article><h1>Release notes</h1><section><h2>CLI only</h2><p>' +
                             BODY + '</p></section><ul><li>' + second + '</li></ul></article>')
        self.assertEqual(result['facts'], ['Release notes\nCLI only\n' + BODY,
                                          'Release notes\n' + second])

    def test_nested_skipped_elements_do_not_hide_or_add_article_content(self):
        result = self.enrich('<main><nav><div><p>Menu text</p></div></nav><article>'
                             '<header><h1>Release notes</h1></header>'
                             '<aside><p>' + BODY.replace('setting', 'advertisement') + '</p></aside>'
                             '<p>' + BODY + '</p><div hidden><p>' + BODY.replace('setting', 'hidden') + '</p>'
                             '</div></article></main>')
        self.assertEqual(result['facts'], ['Release notes\n' + BODY])

    def test_heading_length_cannot_substitute_for_body(self):
        result = self.enrich('<article><h1>' + BODY * 3 + '</h1><p>A short factual paragraph.</p></article>')
        self.assertEqual(result['fetch_reason'], 'insufficient_article_text')

    def test_unclosed_or_oversized_list_is_not_partially_quoted(self):
        for markup in ('<article><ul><li>' + BODY,
                       '<article><ul><li>' + BODY * MAX_EXCERPT_CHARS + '</li></ul></article>'):
            with self.subTest(size=len(markup)):
                result = self.enrich(markup)
                self.assertEqual(result['evidence_status'], 'summary_only')
                self.assertEqual(result['facts'], [])

    def test_modern_application_shell_under_bounded_cap_can_expose_body(self):
        markup = '<script>' + 'x' * 300_000 + '</script><article><p>' + BODY + '</p></article>'
        result = self.enrich(markup)
        self.assertEqual(result['evidence_status'], 'body')
        self.assertEqual(result['facts'], [BODY])

    def test_download_size_limit_is_strict_and_has_fixed_diagnostic(self):
        page = Response('<article><p>' + BODY + '</p></article>' + 'x' * MAX_BYTES)
        session = Mock()
        session.get.side_effect = [robots(), page]
        result = ArticleFetcher(session).enrich({'url': URL})
        self.assertEqual(result['fetch_reason'], 'article_size_limit')
        self.assertEqual(result['evidence_status'], 'summary_only')
        self.assertTrue(page.closed)
        self.assertEqual(result['facts'], [])

    def test_cross_host_redirect_checks_both_robots_and_final_article_date(self):
        target = 'https://blog.google/ai/release'
        page = Response('<script type="application/ld+json">'
                        '{"@type":"Article","url":"' + target + '","datePublished":"2026-11-05"}'
                        '</script><article><p>' + BODY + '</p></article>')
        redirect = Response(status=302, headers={'Location': target})
        session = Mock()
        responses = [robots(), redirect, robots(), page]
        session.get.side_effect = responses
        result = ArticleFetcher(session).enrich({'url': 'https://deepmind.google/blog/release'})
        self.assertEqual(result['evidence_status'], 'body')
        self.assertEqual(result['article_published_date'], '2026-11-05')
        self.assertEqual([c.args[0] for c in session.get.call_args_list], [
            'https://deepmind.google/robots.txt', 'https://deepmind.google/blog/release',
            'https://blog.google/robots.txt', target])
        self.assertTrue(all(r.closed for r in responses))
        for call in session.get.call_args_list:
            self.assertFalse(call.kwargs['allow_redirects'])
            self.assertTrue(call.kwargs['stream'])
            self.assertIn(call.kwargs['timeout'], ((3, 5), (4, 9)))

    def test_redirect_target_robots_denial_prevents_article_request(self):
        session = Mock()
        session.get.side_effect = [robots(), Response(status=302, headers={'Location': 'https://other.example/article'}),
                                   robots('User-agent: *\nDisallow: /')]
        result = ArticleFetcher(session).enrich({'url': URL})
        self.assertEqual(result['fetch_reason'], 'robots_disallowed_or_unavailable')
        self.assertEqual(session.get.call_count, 3)

    def test_redirect_to_unsafe_target_is_rejected_before_any_request_to_it(self):
        for target in ('http://example.com/article', 'https://127.0.0.1/private',
                       'https://169.254.169.254/metadata', 'https://localhost./private',
                       'https://host.internal/private', 'https://example.com:8443/article',
                       'https://user:password@example.com/article'):
            with self.subTest(target=target):
                session = Mock()
                session.get.side_effect = [robots(), Response(status=302, headers={'Location': target})]
                result = ArticleFetcher(session).enrich({'url': URL})
                self.assertEqual(result['fetch_reason'], 'unsafe_article_url')
                self.assertEqual(session.get.call_count, 2)

    def test_redirect_limit_stops_loop_and_closes_every_response(self):
        session = Mock()
        responses = [Response(status=302, headers={'Location': URL}) for _ in range(3)]
        session.get.side_effect = responses
        with self.assertRaisesRegex(EvidenceFetchError, '^redirect_limit$'):
            _bounded_get(session, URL)
        self.assertEqual(session.get.call_count, 3)
        self.assertTrue(all(r.closed for r in responses))

    def test_missing_redirect_location_has_explicit_reason(self):
        session = Mock()
        session.get.side_effect = [robots(), Response(status=302)]
        result = ArticleFetcher(session).enrich({'url': URL})
        self.assertEqual(result['fetch_reason'], 'redirect_missing_location')

    def test_oversized_or_failed_robots_does_not_fetch_article(self):
        for response in (robots('x' * (MAX_ROBOTS_BYTES + 1)), Response(status=503),
                         Response(status=302, headers={'Location': 'https://other.example/robots.txt'})):
            session = Mock()
            session.get.return_value = response
            result = ArticleFetcher(session).enrich({'url': URL})
            self.assertEqual(result['fetch_reason'], 'robots_disallowed_or_unavailable')
            self.assertEqual(session.get.call_count, 1)
            self.assertTrue(response.closed)

    def test_404_robots_permits_public_article_and_caches_rule(self):
        session = Mock()
        response = Response(status=404)
        session.get.side_effect = [response, Response('<article><p>' + BODY + '</p></article>')]
        result = ArticleFetcher(session).enrich({'url': URL})
        self.assertEqual(result['evidence_status'], 'body')
        self.assertEqual(session.get.call_count, 2)
        self.assertTrue(response.closed)

    def test_failures_retain_no_raw_error_or_content(self):
        for response, reason in ((Response(status=403), 'http_403'),
                                 (Response(BODY, headers={'Content-Type': 'application/json'}), 'unsupported_content_type')):
            session = Mock()
            session.get.side_effect = [robots(), response]
            result = ArticleFetcher(session).enrich({'url': URL})
            self.assertEqual(result['fetch_reason'], reason)
            self.assertEqual(result['evidence_excerpts'], [])
            self.assertTrue(response.closed)
        session = Mock()
        session.get.side_effect = [robots(), requests.ReadTimeout('arbitrary private text')]
        self.assertEqual(ArticleFetcher(session).enrich({'url': URL})['fetch_reason'], 'request_timeout')

    def test_malformed_or_unexpected_port_urls_fail_without_network(self):
        for url in ('https://[bad', 'https://example.com:not-a-port', 'https://localhost./',
                    'https://example.com:80/a', 'https://127.1/', 'https://0x7f.0.0.1/',
                    'https://0177.0.0.1/', 'https://2130706433/'):
            self.assertFalse(_safe_public_https(url))
            session = Mock()
            self.assertFalse(ArticleFetcher(session).allowed(url))
            session.get.assert_not_called()


if __name__ == '__main__':
    unittest.main()
