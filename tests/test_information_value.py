"""Information-value and source-coverage contracts. Entirely offline."""
import copy
import json
import unittest

from scripts import editorial


def source(name='copilot'):
    return {
        'source': 'GitHub', 'title': 'Copilot product updates',
        'url': f'https://example.org/{name}', 'date': '2026-11-09',
        'evidence_status': 'body', 'evidence_excerpts': [
            {'id': f'{name}-cli', 'text':
             'Copilot CLI now includes a /settings command for changing configuration.'},
            {'id': f'{name}-agents', 'text':
             'Custom agents are available in Visual Studio Code version 1.106 and later.'},
        ],
    }


def report(first=True, final=False):
    item = source()
    texts = (['こんにちは、MASURADIO 88.8、NANAです。'] if first else []) + [
        'GitHubの発表です。Copilot CLIに、設定を変更する/settingsコマンドが加わりました。',
        '別の利用環境では、カスタムエージェントはVisual Studio Codeのバージョン1.106以降で使えます。',
    ]
    offset = 1 if first else 0
    if final:
        texts.append('また次回お会いしましょう。MASURADIO 88.8、NANAがお届けしました。')
    return {
        'segments': [{'speaker': 'NANA', 'text': t} for t in texts],
        'claims': [{'segment_index': i + offset, 'excerpt_id': excerpt['id'],
                    'quote': excerpt['text']}
                   for i, excerpt in enumerate(item['evidence_excerpts'])],
        'story_points': [{'source_url': item['url'], 'segment_indices': [offset, offset + 1]}],
    }


def second_report():
    item = source('audio')
    item.update(source='Audio Lab', title='Speech model constraints')
    item['evidence_excerpts'] = [
        {'id': 'audio-languages', 'text': 'The model supports English and Spanish speech input.'},
        {'id': 'audio-license', 'text': 'A research-only license excludes commercial use of the model.'},
    ]
    part = {
        'segments': [
            {'speaker': 'NANA', 'text': 'Audio Labの発表によると、このモデルの音声入力は英語とスペイン語に対応します。'},
            {'speaker': 'NANA', 'text': 'ただしライセンスは研究用途に限られ、このモデルを商用には使えません。'},
        ],
        'claims': [{'segment_index': i, 'excerpt_id': e['id'], 'quote': e['text']}
                   for i, e in enumerate(item['evidence_excerpts'])],
        'story_points': [{'source_url': item['url'], 'segment_indices': [0, 1]}],
    }
    return item, part


def combined_report():
    item, extra = second_report()
    part = report()
    offset = len(part['segments'])
    part['segments'].extend(extra['segments'])
    part['claims'].extend(dict(c, segment_index=c['segment_index'] + offset)
                          for c in extra['claims'])
    part['story_points'].append({'source_url': item['url'],
                                 'segment_indices': [offset, offset + 1]})
    return [source(), item], part


class InformationValueTests(unittest.TestCase):
    def validate(self, part, sources=None, previous=None, number=1, final_chapter=False):
        return editorial.validate_editorial(part, [source()] if sources is None else sources,
                                            previous or [], number, 'report', '2026-11-09',
                                            final_chapter=final_chapter)

    def test_plan_reports_only_body_verified_sources_once(self):
        sources = [source(str(i)) for i in range(7)]
        unknown = dict(source('unknown'), evidence_status='summary_only')
        empty = dict(source('empty'), evidence_excerpts=[])
        chapters = editorial.plan_chapters([unknown, sources[0], empty, sources[0]] + sources[1:])
        self.assertEqual([c[1] for c in chapters], ['report', 'report', 'report'])
        self.assertEqual([len(c[2]) for c in chapters], [2, 2, 1])
        self.assertEqual([s for _, _, group in chapters for s in group], sources[:5])

    def test_plan_one_body_story_is_one_report_not_an_exercise(self):
        chapters = editorial.plan_chapters([source()])
        self.assertEqual(len(chapters), 1)
        self.assertEqual(chapters[0][1:], ('report', [source()]))

    def test_plan_fails_without_citable_body_evidence(self):
        cases = [[], [dict(source(), evidence_status='summary_only')],
                 [dict(source(), evidence_excerpts=[])], [dict(source(), url='')]]
        for sources in cases:
            with self.subTest(sources=sources), self.assertRaisesRegex(ValueError, 'No body-confirmed'):
                editorial.plan_chapters(sources)

    def test_report_accepts_two_distinct_supported_facts_and_known_condition(self):
        self.assertTrue(self.validate(report()))
        self.assertTrue(self.validate(report(first=False)))
        self.assertTrue(self.validate(report(final=True), final_chapter=True))

    def test_every_assigned_source_has_its_own_two_fact_segments(self):
        sources, part = combined_report()
        self.assertTrue(self.validate(part, sources))
        part['story_points'].pop()
        with self.assertRaisesRegex(ValueError, 'exactly one entry'):
            self.validate(part, sources)

    def test_missing_or_malformed_story_ledger_is_rejected(self):
        for ledger in (None, {}, [], ['not an object']):
            part = report()
            part['story_points'] = ledger
            with self.subTest(ledger=ledger), self.assertRaisesRegex(ValueError, 'story_points'):
                self.validate(part)
        part = report()
        del part['story_points']
        with self.assertRaisesRegex(ValueError, 'story_points'):
            self.validate(part)

    def test_two_distinct_valid_integer_indices_are_required(self):
        for indices in ([1], [1, 1], [True, 2], [1, -1], [1, 3], [1, '2'], '1,2', None):
            part = report()
            part['story_points'][0]['segment_indices'] = indices
            with self.subTest(indices=indices), self.assertRaisesRegex(ValueError, 'distinct fact segments'):
                self.validate(part)

    def test_ledger_cannot_count_uncited_opening_as_a_fact(self):
        part = report()
        part['story_points'][0]['segment_indices'] = [0, 1]
        with self.assertRaisesRegex(ValueError, 'own source'):
            self.validate(part)

    def test_ledger_must_name_exact_assigned_source(self):
        for url in ('https://example.org/wrong', '', None, []):
            part = report()
            part['story_points'][0]['source_url'] = url
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, 'source_url'):
                self.validate(part)

    def test_repeating_one_source_cannot_hide_a_missing_story(self):
        sources, part = combined_report()
        part['story_points'][1] = copy.deepcopy(part['story_points'][0])
        with self.assertRaisesRegex(ValueError, 'repeated source_url'):
            self.validate(part, sources)

    def test_claim_from_another_valid_source_cannot_cover_this_story(self):
        sources, part = combined_report()
        # The replacement is a globally valid exact quote, but from the wrong article.
        part['claims'][-1] = dict(part['claims'][0], segment_index=4)
        with self.assertRaisesRegex(ValueError, 'own source'):
            self.validate(part, sources)

    def test_colliding_excerpt_ids_do_not_lose_or_cross_bind_sources(self):
        sources, part = combined_report()
        for i in range(2):
            sources[1]['evidence_excerpts'][i]['id'] = sources[0]['evidence_excerpts'][i]['id']
            part['claims'][i + 2]['excerpt_id'] = sources[0]['evidence_excerpts'][i]['id']
        self.assertTrue(self.validate(part, sources))
        part['claims'][-1]['quote'] = sources[0]['evidence_excerpts'][1]['text']
        with self.assertRaisesRegex(ValueError, 'own source'):
            self.validate(part, sources)

    def test_fabricated_quote_or_excerpt_id_still_fails(self):
        for field, value in (('quote', 'A newly invented feature that does not exist.'),
                             ('excerpt_id', 'invented-id'), ('segment_index', True)):
            part = report()
            part['claims'][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'exact excerpt'):
                self.validate(part)

    def test_no_citations_is_not_a_news_report(self):
        part = report()
        part['claims'] = []
        with self.assertRaisesRegex(ValueError, 'sourced claims'):
            self.validate(part)

    def test_unknown_or_empty_evidence_cannot_support_story_points(self):
        for item in (dict(source(), evidence_status='summary_only'),
                     dict(source(), evidence_excerpts=[])):
            with self.subTest(item=item), self.assertRaisesRegex(ValueError, 'exact excerpt'):
                self.validate(report(), [item])

    def test_duplicate_assigned_sources_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'distinct body-confirmed'):
            self.validate(report(), [source(), source()])

    def test_final_report_can_identify_station_only_in_farewell(self):
        part = report(first=False, final=True)
        self.assertTrue(self.validate(part, number=2, final_chapter=True))
        with self.assertRaisesRegex(ValueError, 'station-announcement'):
            self.validate(part, number=2)
        part['segments'].insert(1, part['segments'].pop())
        with self.assertRaisesRegex(ValueError, 'station-announcement'):
            self.validate(part, number=2, final_chapter=True)

    def test_farewell_does_not_exempt_a_statistic_with_the_station_number(self):
        part = report(first=False, final=True)
        part['segments'][-1]['text'] += '作業時間を88.8パーセント減らせます。'
        with self.assertRaisesRegex(ValueError, 'number missing'):
            self.validate(part, number=2, final_chapter=True)

    def test_real_greetings_and_host_introductions_remain_rejected(self):
        for text, marker in (
            ('こんにちは。MASURADIO 88.8、また次回お会いしましょう。', 'audience-greeting'),
            ('MASURADIO 88.8、NANAです。また次回お会いしましょう。', 'host-introduction'),
            ('MASURADIO 88.8、入力例は「また次回お会いしましょう」です。', 'station-announcement'),
        ):
            part = report(first=False, final=True)
            part['segments'][-1]['text'] = text
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, marker):
                self.validate(part, number=2, final_chapter=True)

    def test_quoted_greeting_sample_is_not_a_second_intro(self):
        part = report(first=False)
        part['segments'].append({'speaker': 'NANA', 'text': '入力する例文は「こんにちは」です。'})
        self.assertTrue(self.validate(part, number=2))

    def test_previous_fact_cannot_be_repeated_in_a_later_chapter(self):
        part = report(first=False)
        with self.assertRaisesRegex(ValueError, 'Repeated segment'):
            self.validate(part, previous=[part['segments'][0]], number=2)

    def test_uncited_numbers_are_still_rejected(self):
        part = report()
        part['segments'][1]['text'] += '処理速度は123倍です。'
        with self.assertRaisesRegex(ValueError, 'number missing'):
            self.validate(part)

    def test_prompt_leads_with_news_not_a_weekday_theme_or_practice(self):
        prompt = editorial.chapter_prompt('2026-11-09', 1, editorial.plan_chapters([source()]),
                                          '月曜：AIモデル・研究', 'direction', [], [])
        for expected in ('Write 2-9 segments', 'NOT a mandatory spoken theme', 'story_points',
                         'TWO distinct useful facts', 'THAT source URL', 'Never pad',
                         'Do not append a practice chapter', '/settings', 'Install Copilot CLI'):
            self.assertIn(expected, prompt)
        self.assertNotIn('Aim 700-1100', prompt)
        self.assertNotIn('For practice: apply', prompt)
        self.assertNotIn('For brief: mention', prompt)

    def test_prior_script_and_full_evidence_are_in_continuation_prompt(self):
        chapters = editorial.plan_chapters([source(str(i)) for i in range(3)])
        previous = report()['segments']
        prompt = editorial.chapter_prompt('2026-11-09', 2, chapters, 'focus', 'direction', [], previous)
        self.assertIn(previous[1]['text'], prompt)
        self.assertIn('https://example.org/2', prompt)
        self.assertIn('S1E1', prompt)
        self.assertNotIn('"id": "0-cli"', prompt)
        self.assertIn('context, NOT evidence', prompt)
        self.assertIn('only the length needed', prompt)

    def test_audit_checks_usefulness_conditions_scope_and_unsupported_hype(self):
        chapters = editorial.plan_chapters([source()])
        prompt = editorial.audit_prompt([report()], chapters)
        for expected in ('TWO DISTINCT useful', 'OWN assigned source', 'Rephrasing the same fact',
                         'missing material conditions', 'preview vs generally available',
                         'improved productivity', 'Copilot CLI /settings', 'newly announced CLI release',
                         'irrelevant weekday-theme', 'padding to reach a duration'):
            self.assertIn(expected, prompt)
        payload = json.loads(prompt.split('\n')[-1])
        self.assertTrue(payload[0]['final_chapter'])
        self.assertEqual(payload[0]['draft']['story_points'], report()['story_points'])
        self.assertEqual(payload[0]['evidence'][0]['excerpts'], source()['evidence_excerpts'])

    def test_audit_cannot_silently_truncate_unreviewed_chapters(self):
        with self.assertRaisesRegex(ValueError, 'every planned chapter'):
            editorial.audit_prompt([], editorial.plan_chapters([source()]))


if __name__ == '__main__':
    unittest.main()
