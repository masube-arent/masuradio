"""Deterministic citation binding. Offline; no writer or audit API calls."""
import copy
import json
import unittest

from scripts import editorial


def sources():
    return [
        {'source': 'GitHub', 'title': 'Copilot release notes',
         'url': 'https://example.org/copilot', 'date': '2026-11-09',
         'article_published_date': '2026-11-08', 'evidence_status': 'body',
         'evidence_excerpts': [
             {'id': 'stable-cli', 'text':
              'Copilot CLI\nThe /settings command changes configuration in Copilot CLI only.',
              'heading': 'Copilot CLI'},
             {'id': 'stable-version', 'text':
              'Custom agents require Visual Studio Code version 1.106 or later. '
              'This preview is limited to eligible paid accounts; other surfaces are excluded.'},
         ]},
        {'source': 'Audio Lab', 'title': 'Speech model release',
         'url': 'https://example.org/audio', 'date': '2026-11-09',
         'evidence_status': 'body', 'evidence_excerpts': [
             # Deliberately collide with the first article's original stable IDs.
             {'id': 'stable-cli', 'text':
              'The speech model accepts English and Spanish audio as input.'},
             {'id': 'stable-version', 'text':
              'This model has a research-only license; commercial use is not permitted.'},
         ]},
    ]


def draft():
    return {
        'segments': [
            {'speaker': 'NANA', 'text': 'Copilot CLIに、設定を変更する/settingsコマンドが加わりました。'},
            {'speaker': 'NANA', 'text': 'カスタムエージェントのプレビューはVisual Studio Code 1.106以降で、対象の有料アカウントに限られます。'},
            {'speaker': 'NANA', 'text': 'Audio Labの音声モデルは、英語とスペイン語の音声を入力できます。'},
            {'speaker': 'NANA', 'text': 'この音声モデルは研究用のライセンスで、商用利用は認められていません。'},
        ],
        'claims': [{'segment_index': index, 'excerpt_id': alias}
                   for index, alias in enumerate(('S1E1', 'S1E2', 'S2E1', 'S2E2'))],
        'story_points': [
            {'source_url': 'https://example.org/copilot', 'segment_indices': [0, 1]},
            {'source_url': 'https://example.org/audio', 'segment_indices': [2, 3]},
        ],
        'episode_title': 'コーディング支援の更新と音声モデルの条件',
    }


def validate(part, evidence=None):
    return editorial.validate_editorial(part, evidence or sources(), [], 1, 'report', '2026-11-09')


class CitationBindingTests(unittest.TestCase):
    def test_writer_aliases_are_ordered_local_and_do_not_mutate_evidence(self):
        evidence = sources()
        original = copy.deepcopy(evidence)
        writer = editorial.writer_evidence(evidence)
        self.assertEqual([[e['id'] for e in s['excerpts']] for s in writer],
                         [['S1E1', 'S1E2'], ['S2E1', 'S2E2']])
        self.assertEqual(editorial.writer_evidence(evidence), writer)
        self.assertEqual(editorial.writer_evidence(evidence[1:])[0]['excerpts'][0]['id'], 'S1E1')
        self.assertEqual(evidence, original)
        for actual, expected in zip(writer, editorial.source_evidence(evidence)):
            self.assertEqual({k: v for k, v in actual.items() if k != 'excerpts'},
                             {k: v for k, v in expected.items() if k != 'excerpts'})
            for a, e in zip(actual['excerpts'], expected['excerpts']):
                self.assertEqual({k: v for k, v in a.items() if k != 'id'},
                                 {k: v for k, v in e.items() if k != 'id'})

    def test_bind_restores_stable_ids_and_full_exact_text_for_each_source(self):
        evidence, part = sources(), draft()
        original = copy.deepcopy(part)
        bound = editorial.bind_claims(part, evidence)
        self.assertIsNot(bound, part)
        self.assertEqual(part, original)
        self.assertTrue(validate(bound))
        for index, claim in enumerate(bound['claims']):
            source, excerpt = evidence[index // 2], evidence[index // 2]['evidence_excerpts'][index % 2]
            self.assertEqual(claim, {'segment_index': index, 'excerpt_id': excerpt['id'],
                                     'quote': excerpt['text'], 'source_url': source['url']})
            self.assertIsNot(claim, part['claims'][index])
        self.assertEqual(bound['story_points'], part['story_points'])
        self.assertEqual(bound['episode_title'], part['episode_title'])
        self.assertEqual(editorial.bind_claims(bound, evidence), bound)

    def test_long_unicode_excerpt_is_attached_byte_for_byte_not_copied_by_writer(self):
        evidence, part = sources(), draft()
        full = ('Product heading\r\n' + 'The “preview” is limited to paid users; 使用条件を維持します。 ' * 70
                + '\r\nNo access is available on other product surfaces.')
        evidence[0]['evidence_excerpts'][0]['text'] = full
        bound = editorial.bind_claims(part, evidence)
        self.assertEqual(bound['claims'][0]['quote'].encode(), full.encode())
        self.assertIn('No access is available on other product surfaces.', bound['claims'][0]['quote'])

    def test_every_claim_for_a_multi_excerpt_segment_is_bound(self):
        part = draft()
        part['claims'].append({'segment_index': 0, 'excerpt_id': 'S1E2'})
        bound = editorial.bind_claims(part, sources())
        self.assertEqual(len(bound['claims']), 5)
        self.assertEqual(bound['claims'][-1]['quote'], sources()[0]['evidence_excerpts'][1]['text'])

    def test_invalid_segment_indices_are_rejected_without_echoing_input(self):
        for index in (-1, 4, True, False, 0.0, 'PRIVATE-INDEX', [], {}, None):
            part = draft()
            part['claims'][0]['segment_index'] = index
            with self.subTest(index=index), self.assertRaisesRegex(
                    ValueError, 'claim_index=0, marker=invalid-segment-index') as caught:
                editorial.bind_claims(part, sources())
            self.assertNotIn('PRIVATE-INDEX', str(caught.exception))

    def test_missing_unknown_or_malformed_references_are_not_guessed(self):
        for reference in ('S3E1', 'S1E99', 's1e1', ' S1E1 ', 'stable-cli',
                          'PRIVATE-REFERENCE', '', [], {}, 1, True, None):
            part = draft()
            part['claims'][1]['excerpt_id'] = reference
            with self.subTest(reference=reference), self.assertRaisesRegex(
                    ValueError, 'claim_index=1, marker=(unknown|invalid)-excerpt-id') as caught:
                editorial.bind_claims(part, sources())
            self.assertNotIn('PRIVATE-REFERENCE', str(caught.exception))
        part = draft()
        del part['claims'][0]['excerpt_id']
        with self.assertRaisesRegex(ValueError, 'invalid-excerpt-id'):
            editorial.bind_claims(part, sources())

    def test_malformed_claims_and_ledgers_fail_closed(self):
        for claims in (None, {}, 'PRIVATE-LEDGER'):
            with self.subTest(claims=claims), self.assertRaisesRegex(ValueError, 'claim evidence ledger'):
                editorial.bind_claims(dict(draft(), claims=claims), sources())
        for claim in (None, [], 'PRIVATE-CLAIM'):
            part = draft()
            part['claims'][2] = claim
            with self.subTest(claim=claim), self.assertRaisesRegex(
                    ValueError, 'claim_index=2, marker=invalid-claim') as caught:
                editorial.bind_claims(part, sources())
            self.assertNotIn('PRIVATE-CLAIM', str(caught.exception))
        for part in (None, [], {}, {'segments': 'PRIVATE-SEGMENTS', 'claims': []}):
            with self.subTest(part=part), self.assertRaisesRegex(ValueError, 'missing-segments'):
                editorial.bind_claims(part, sources())

    def test_non_body_and_missing_evidence_never_get_aliases(self):
        evidence = sources()
        evidence[0]['evidence_status'] = 'summary_only'
        self.assertEqual(editorial.writer_evidence(evidence)[0]['excerpts'], [])
        self.assertEqual(editorial.writer_evidence(evidence)[1]['excerpts'][0]['id'], 'S2E1')
        for evidence in ([], evidence):
            with self.subTest(evidence=evidence), self.assertRaisesRegex(ValueError, 'unknown-excerpt-id'):
                editorial.bind_claims(draft(), evidence)
        self.assertEqual(editorial.bind_claims({'segments': [], 'claims': []}, [])['claims'], [])

    def test_wrong_supplied_quote_is_never_silently_repaired(self):
        for quote in ('Invented availability and a PRIVATE-QUOTE that is not supported.',
                      sources()[1]['evidence_excerpts'][0]['text'],
                      sources()[0]['evidence_excerpts'][0]['text'].replace('\n', ' '),
                      None, [], 42, '', 'too short'):
            part = draft()
            part['claims'][0]['quote'] = quote
            original = copy.deepcopy(part)
            with self.subTest(quote=quote), self.assertRaisesRegex(
                    ValueError, 'claim_index=0, marker=(provided-quote-mismatch|invalid-provided-quote)') as caught:
                editorial.bind_claims(part, sources())
            self.assertEqual(part, original)
            self.assertNotIn('PRIVATE-QUOTE', str(caught.exception))

    def test_exact_explicit_quotes_may_be_bound_but_all_context_is_preserved(self):
        for reference in ('S1E2', 'stable-version'):
            part = draft()
            part['claims'][1].update(excerpt_id=reference,
                                     quote='Custom agents require Visual Studio Code version 1.106 or later.')
            bound = editorial.bind_claims(part, sources())
            self.assertTrue(validate(bound))
            self.assertEqual(bound['claims'][1]['quote'], sources()[0]['evidence_excerpts'][1]['text'])
            self.assertIn('limited to eligible paid accounts', bound['claims'][1]['quote'])

    def test_legacy_wrong_quotes_and_unknown_ids_still_fail(self):
        for reference, quote in (
            ('stable-cli', 'Invented unsupported attribution to a developer.'),
            ('missing-stable-id', sources()[0]['evidence_excerpts'][0]['text']),
            ('S9E9', sources()[0]['evidence_excerpts'][0]['text']),
        ):
            part = draft()
            part['claims'][0].update(excerpt_id=reference, quote=quote)
            with self.subTest(reference=reference), self.assertRaisesRegex(ValueError, 'provided-quote-mismatch'):
                editorial.bind_claims(part, sources())

    def test_alias_collision_with_stable_id_never_falls_back_to_a_different_source(self):
        evidence, part = sources(), draft()
        evidence[1]['evidence_excerpts'][0]['id'] = 'S1E1'
        # The explicit quote would match the second article's contrived stable
        # ID, but S1E1 always references the first supplied article/excerpt.
        part['claims'][0]['quote'] = evidence[1]['evidence_excerpts'][0]['text']
        with self.assertRaisesRegex(ValueError, 'provided-quote-mismatch'):
            editorial.bind_claims(part, evidence)
        del part['claims'][0]['quote']
        bound = editorial.bind_claims(part, evidence)
        self.assertEqual(bound['claims'][0]['excerpt_id'], 'stable-cli')
        self.assertEqual(bound['claims'][0]['source_url'], evidence[0]['url'])
        self.assertEqual(bound['claims'][2]['excerpt_id'], 'S1E1')
        self.assertEqual(bound['claims'][2]['source_url'], evidence[1]['url'])

    def test_malformed_evidence_fails_with_positions_only(self):
        for excerpt in (None, {}, {'id': [], 'text': 'PRIVATE-EVIDENCE'},
                        {'id': 'PRIVATE-ID', 'text': []}, {'id': 'PRIVATE-ID', 'text': 'short'}):
            evidence = sources()
            evidence[0]['evidence_excerpts'][0] = excerpt
            with self.subTest(excerpt=excerpt), self.assertRaisesRegex(
                    ValueError, 'Invalid citation evidence: source_index=1, excerpt_index=1') as caught:
                editorial.bind_claims(draft(), evidence)
            self.assertNotIn('PRIVATE-', str(caught.exception))

    def test_foreign_source_url_cannot_override_an_alias(self):
        for url in (sources()[1]['url'], 'PRIVATE-SOURCE', None, []):
            part = draft()
            part['claims'][0]['source_url'] = url
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, 'marker=foreign-source') as caught:
                editorial.bind_claims(part, sources())
            self.assertNotIn('PRIVATE-SOURCE', str(caught.exception))

    def test_foreign_alias_cannot_satisfy_another_story_ledger(self):
        part = draft()
        part['claims'][2]['excerpt_id'] = 'S1E1'
        with self.assertRaisesRegex(ValueError, 'own source'):
            validate(editorial.bind_claims(part, sources()))

    def test_identical_ids_and_text_still_preserve_article_identity(self):
        evidence, part = sources(), draft()
        evidence[1]['evidence_excerpts'][0] = copy.deepcopy(evidence[0]['evidence_excerpts'][0])
        bound = editorial.bind_claims(part, evidence)
        self.assertNotEqual(bound['claims'][0]['source_url'], bound['claims'][2]['source_url'])
        part['claims'][2]['excerpt_id'] = 'S1E1'
        with self.assertRaisesRegex(ValueError, 'own source'):
            validate(editorial.bind_claims(part, evidence), evidence)

    def test_ambiguous_legacy_id_and_quote_are_not_guessed(self):
        evidence, part = sources(), draft()
        evidence[1]['evidence_excerpts'][0] = copy.deepcopy(evidence[0]['evidence_excerpts'][0])
        part['claims'][0].update(excerpt_id='stable-cli',
                                 quote=evidence[0]['evidence_excerpts'][0]['text'])
        with self.assertRaisesRegex(ValueError, 'ambiguous-excerpt-id'):
            editorial.bind_claims(part, evidence)
        part['claims'][0]['source_url'] = evidence[0]['url']
        bound = editorial.bind_claims(part, evidence)
        self.assertEqual(bound['claims'][0]['source_url'], evidence[0]['url'])

    def test_bound_quote_and_source_still_pass_through_exact_validation(self):
        for field, value in (('quote', 'An invented quote not contained in any evidence.'),
                             ('excerpt_id', 'not-a-real-id'),
                             ('source_url', sources()[1]['url'])):
            part = editorial.bind_claims(draft(), sources())
            part['claims'][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'exact excerpt support'):
                validate(part)

    def test_numeric_binding_is_unchanged_and_diagnostics_do_not_echo_draft(self):
        for text in ('今日は987件のニュースです。PRIVATE-SPEECH',
                     '処理速度は987倍になりました。PRIVATE-SPEECH'):
            part = draft()
            part['segments'][2]['text'] = text
            with self.subTest(text=text), self.assertRaisesRegex(
                    ValueError, 'Spoken number missing from cited evidence: '
                    'chapter=1, segment_index=2, marker=uncited-number') as caught:
                validate(editorial.bind_claims(part, sources()))
            self.assertNotIn('987', str(caught.exception))
            self.assertNotIn('PRIVATE-SPEECH', str(caught.exception))
            self.assertIn('avoid unsourced agenda/list counts', str(caught.exception))

    def test_writer_prompt_requests_references_and_full_semantic_audit_keeps_originals(self):
        evidence = sources()
        chapters = [('News', 'report', evidence)]
        prompt = editorial.chapter_prompt('2026-11-09', 1, chapters, 'focus', 'direction', [], [])
        self.assertIn('{"segment_index":0,"excerpt_id":"S1E1"}', prompt)
        self.assertIn('Do NOT output a quote', prompt)
        self.assertIn('Do not announce unsourced agenda/list counts', prompt)
        self.assertIn('TWO distinct useful facts', prompt)
        self.assertIn('THAT source URL', prompt)
        self.assertNotIn('stable-cli', prompt)
        self.assertNotIn('exact supporting excerpt substring', prompt)
        for source in evidence:
            for excerpt in source['evidence_excerpts']:
                self.assertIn(json.dumps(excerpt['text'], ensure_ascii=False), prompt)
        bound = editorial.bind_claims(draft(), evidence)
        audit = editorial.audit_prompt([bound], chapters)
        payload = json.loads(audit.split('\n')[-1])
        self.assertEqual(payload[0]['evidence'], editorial.source_evidence(evidence))
        self.assertEqual(payload[0]['draft'], bound)
        self.assertNotIn('S1E1', audit)
        self.assertIn('the quote must\nactually support the Japanese statement', audit)
        self.assertIn('Reject missing material conditions', audit)
        self.assertIn('Check every factual statement', audit)


if __name__ == '__main__':
    unittest.main()
