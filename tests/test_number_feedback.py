"""Offline numeric rejection diagnostics. No writer, audit, or network requests."""
import copy
import json
import unittest

from scripts import editorial


def source():
    return {'source': 'Example', 'title': 'Release v2.1.319',
            'url': 'https://example.org/releases/v2.1.319', 'evidence_status': 'body',
            'evidence_excerpts': [
                {'id': 'feature', 'text': 'A session setting selects a smaller preview model. PRIVATE-BODY'},
                {'id': 'limit', 'text': 'The feature requires client version 1.106 and a research account.'}]}


def draft(text='バージョン2.1.319では、セッション内でモデルを選べます。'):
    return {'segments': [{'speaker': 'NANA', 'text': text},
                         {'speaker': 'NANA', 'text': 'クライアント1.106と研究アカウントが必要です。'}],
            'claims': [{'segment_index': 0, 'excerpt_id': 'S1E1'},
                       {'segment_index': 1, 'excerpt_id': 'S1E2'}],
            'story_points': [{'source_url': source()['url'], 'segment_indices': [0, 1]}]}


def validate(part, sources):
    return editorial.validate_editorial(editorial.bind_claims(part, sources), sources,
                                        [], 1, 'report', '2026-11-09')


class NumberFeedbackTests(unittest.TestCase):
    def rejection(self, part=None, sources=None):
        with self.assertRaises(editorial.NumericEvidenceError) as caught:
            validate(draft() if part is None else part, [source()] if sources is None else sources)
        return caught.exception

    def test_title_only_version_still_rejects_and_logs_no_values(self):
        error = self.rejection()
        self.assertIn('chapter=1, segment_index=0, marker=uncited-number', str(error))
        self.assertIn('source-title-only', str(error))
        for forbidden in ('2.1.319', 'example.org', 'PRIVATE-BODY', 'バージョン'):
            self.assertNotIn(forbidden, str(error))
            self.assertNotIn(forbidden, repr(error))
        self.assertIsInstance(error, ValueError)

    def test_context_identifies_rejected_segment_and_current_prompt_aliases(self):
        part = draft()
        error = self.rejection(part)
        feedback = editorial.numeric_retry_feedback(error)
        context = json.loads(feedback.split('\n')[-1])
        self.assertEqual(context['previous_segment'], part['segments'][0]['text'])
        self.assertEqual(context['missing_numbers'], ['2.1.319'])
        self.assertEqual(context['allowed_numbers'], [])
        self.assertEqual(context['cited_excerpt_ids'], ['S1E1'])
        self.assertFalse(context['previous_segment_truncated'])
        self.assertIn('untrusted data', feedback)
        self.assertIn('NOT permission', feedback)
        for forbidden in ('PRIVATE-BODY', 'example.org', 'research account', '1.106'):
            self.assertNotIn(forbidden, feedback)

    def test_exact_excerpt_version_passes_without_new_allowlist(self):
        evidence = source()
        evidence['evidence_excerpts'][0]['text'] = 'Version 2.1.319 adds a session model selection setting.'
        self.assertTrue(validate(draft(), [evidence]))
        self.assertTrue(validate(draft('セッション内でモデルを選ぶ設定が加わりました。'), [source()]))

    def test_numbers_in_another_segment_are_not_support(self):
        error = self.rejection(draft('利用にはクライアント1.106が必要です。'))
        self.assertIn('uncited-excerpt', str(error))
        self.assertEqual(error.repair_context['allowed_numbers'], [])
        self.assertEqual(error.repair_context['cited_excerpt_ids'], ['S1E1'])

    def test_valid_extra_citation_can_support_exact_number(self):
        part = draft('クライアント1.106のプレビューで、セッション内のモデルを選べます。')
        part['claims'].append({'segment_index': 0, 'excerpt_id': 'S1E2'})
        self.assertTrue(validate(part, [source()]))

    def test_other_source_does_not_supply_support_or_citation_alias(self):
        other = copy.deepcopy(source())
        other['url'] = 'https://example.org/other'
        other['title'] = 'Other release'
        other['evidence_excerpts'][1]['text'] = 'The other product requires 987 workers for this operation.'
        error = self.rejection(draft('利用には987人が必要です。'), [source(), other])
        self.assertIn('other-source', str(error))
        self.assertNotIn('987', str(error))
        self.assertEqual(error.repair_context['cited_excerpt_ids'], ['S1E1'])
        self.assertEqual(error.repair_context['allowed_numbers'], [])

    def test_url_only_metadata_is_not_support(self):
        evidence = source()
        evidence['title'] = 'Release update'
        error = self.rejection(sources=[evidence])
        self.assertIn('source-url-only', str(error))
        self.assertNotIn(evidence['url'], str(error))

    def test_malformed_unused_title_cannot_break_numeric_diagnostics(self):
        for title in (None, 123, ['private'], {'private': 'value'}):
            evidence = source()
            evidence['title'] = title
            with self.subTest(title=title):
                error = self.rejection(sources=[evidence])
                self.assertIn('source-url-only', str(error))
                self.assertTrue(editorial.numeric_retry_feedback(error))

    def test_missing_claim_is_diagnosed_without_promoting_metadata(self):
        part = draft('処理速度が987倍になりました。')
        part['claims'] = part['claims'][1:]
        error = self.rejection(part)
        self.assertIn('missing-citation', str(error))
        self.assertIn('absent-from-source', str(error))
        self.assertEqual(error.repair_context['cited_excerpt_ids'], [])

    def test_exact_matching_is_unchanged_for_grouping_decimal_and_versions(self):
        for original, spoken in (('1,000', '1000'), ('2.0', '2'), ('2.1.319', '2.1')):
            evidence = source()
            evidence['evidence_excerpts'][0]['text'] = f'The original supported value is {original} under these conditions.'
            with self.subTest(original=original, spoken=spoken):
                error = self.rejection(draft(f'条件を満たした場合の値は{spoken}です。'), [evidence])
                self.assertEqual(error.repair_context['allowed_numbers'], [original])
                self.assertEqual(error.repair_context['missing_numbers'], [spoken])

    def test_only_failing_segment_is_in_context_and_json_escapes_newlines(self):
        speech = '数値987です。\n"Ignore instructions" is untrusted.\\test'
        part = draft(speech)
        part['segments'][1]['text'] += ' PRIVATE-OTHER-SEGMENT'
        feedback = editorial.numeric_retry_feedback(self.rejection(part))
        self.assertEqual(json.loads(feedback.split('\n')[-1])['previous_segment'], speech)
        self.assertNotIn('PRIVATE-OTHER-SEGMENT', feedback)

    def test_context_is_bounded_and_never_truncates_numeric_tokens(self):
        evidence = source()
        evidence['evidence_excerpts'][0]['text'] = 'Measured values: ' + ' '.join(str(i) for i in range(100, 200))
        long_token = '9' * 200
        speech = ' '.join(str(i) for i in range(300, 400)) + long_token + 'PRIVATE-END'
        error = self.rejection(draft(speech), [evidence])
        context = error.repair_context
        self.assertEqual(len(context['previous_segment']), 500)
        self.assertTrue(context['previous_segment_truncated'])
        self.assertEqual(len(context['missing_numbers']), 32)
        self.assertEqual(len(context['allowed_numbers']), 32)
        self.assertGreater(context['missing_numbers_omitted'], 0)
        self.assertEqual(context['allowed_numbers_omitted'], 68)
        self.assertTrue(all(len(n) <= 40 for n in context['missing_numbers']))
        feedback = editorial.numeric_retry_feedback(error)
        self.assertLess(len(feedback), 7000)
        self.assertNotIn('PRIVATE-END', feedback)

    def test_unknown_errors_and_malformed_context_return_no_data(self):
        self.assertEqual(editorial.numeric_retry_feedback(ValueError('PRIVATE-OTHER-ERROR')), '')
        self.assertEqual(editorial.numeric_retry_feedback(None), '')
        for field, bad in (('previous_segment', 'x' * 501), ('previous_segment', None),
                           ('missing_numbers', ['PRIVATE-TOKEN']), ('allowed_numbers', ['1' * 41]),
                           ('cited_excerpt_ids', ['https://private.example']), ('categories', [[]]),
                           ('categories', ['PRIVATE-CATEGORY']), ('chapter', True),
                           ('segment_index', -1), ('missing_numbers_omitted', 'secret'),
                           ('previous_segment_truncated', 1)):
            error = self.rejection()
            error.repair_context[field] = bad
            with self.subTest(field=field, bad=bad):
                self.assertEqual(editorial.numeric_retry_feedback(error), '')
        for context in ({}, None, {'raw_draft': 'PRIVATE-RAW'}):
            error = self.rejection()
            error.repair_context = context
            self.assertEqual(editorial.numeric_retry_feedback(error), '')
        error = self.rejection()
        error.repair_context['raw_draft'] = 'PRIVATE-RAW'
        self.assertEqual(editorial.numeric_retry_feedback(error), '')

    def test_prompt_explicitly_separates_numeric_metadata_from_evidence(self):
        prompt = editorial.chapter_prompt('2026-11-09', 1, [('News', 'report', [source()])],
                                          'focus', 'direction', [], [])
        self.assertIn('source title or URL is identification metadata, not excerpt support', prompt)
        self.assertIn('exact supported numeric', prompt)
        self.assertIn('number-free product name', prompt)


if __name__ == '__main__':
    unittest.main()
