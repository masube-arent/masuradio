import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import editorial, generate
from scripts.stage_resume import StageCache, digest
from editorial_fixtures import draft, response, report_draft


SOURCE = {'source': 'Hugging Face', 'title': 'Phonon', 'url': 'https://example.org/phonon',
          'date': '2026-11-07', 'article_published_date': '2026-11-06',
          'evidence_status': 'body', 'evidence_excerpts': [
              {'id': 'phonon-1', 'text': 'Phonon is developed by Gradium and presented on Hugging Face.'},
              {'id': 'review-1', 'text': 'Review-stage dwell time increased by 441% compared with the baseline.'}]}


class EditorialContractTests(unittest.TestCase):
    def test_reporting_allocations_are_disjoint_without_forced_practice(self):
        sources = [dict(SOURCE, url=f'https://example.org/{i}') for i in range(5)]
        chapters = editorial.plan_chapters(sources)
        reported = [s['url'] for _, role, group in chapters for s in group]
        self.assertEqual(len(reported), len(set(reported)))
        self.assertEqual(set(reported), {s['url'] for s in sources})
        self.assertTrue(all(c[1] == 'report' for c in chapters))

    def test_prompt_preserves_prior_script_dates_and_attribution_rules(self):
        chapters = editorial.plan_chapters([SOURCE])
        prompt = editorial.chapter_prompt('2026-11-08', 1, chapters, 'focus', 'direction', [], draft()['segments'])
        for expected in ('441%', 'Gradium', 'reviewer work time', '2026-11-06', 'feed_date',
                         'License', 'Japanese', draft()['segments'][1]['text']):
            self.assertIn(expected, prompt)
        self.assertIn('not a 441% reduction', prompt)

    def test_unknown_body_does_not_authorize_reporting(self):
        with self.assertRaises(ValueError):
            editorial.plan_chapters([dict(SOURCE, evidence_status='summary_only')])
        self.assertEqual(editorial.source_evidence([dict(SOURCE, evidence_status='summary_only')])[0]['excerpts'], [])

    def test_brief_template_handles_zero_one_and_many_headlines(self):
        for count in (0, 1, 3, 7):
            sources = [{'title': f'未確認の記事見出し {i}'} for i in range(count)]
            part = editorial.brief_draft('2026-11-09', sources, '月曜：AIの研究', has_report=False)
            with self.subTest(count=count):
                generate.validate_segments(part['segments'])
                editorial.validate_editorial(part, sources, [], 1, 'brief')
                self.assertEqual(part['claims'], [])
                self.assertEqual(len(part['segments']), 5 + max(1, min(count, 3)))
                spoken = '\n'.join(s['text'] for s in part['segments'])
                self.assertIn('記事本文を確認できていない見出し', spoken)
                self.assertNotIn('記事本文で根拠を確認できた話題', spoken)
                self.assertIn('出典を自分で確かめる練習', spoken)

    def test_brief_skips_unusable_titles_without_slicing_or_repeating_them(self):
        for title in (None, '', 'x' * 161, 'https://example.org/news', '<b>ニュース</b>'):
            with self.subTest(title=title):
                part = editorial.brief_draft('2026-11-09', [{'title': title}], 'AIの研究')
                self.assertIn('読み上げられる見出しを確認できませんでした', part['segments'][3]['text'])
                generate.validate_segments(part['segments'])
        part = editorial.brief_draft('2026-11-09',
                                    [{'title': 'ＡＩ News'}, {'title': 'AI  News'}], 'AIの研究')
        self.assertEqual(len(part['segments']), 6)

    def test_brief_rejects_all_excerpt_claims_even_when_an_excerpt_exists(self):
        part = editorial.brief_draft('2026-11-09', [SOURCE], 'AIの研究')
        part['claims'] = [{'segment_index': 3, 'excerpt_id': 'phonon-1',
                           'quote': SOURCE['evidence_excerpts'][0]['text']}]
        with self.assertRaisesRegex(ValueError, 'Headline-only brief.*claims must be'):
            editorial.validate_editorial(part, [SOURCE], [], 1, 'brief')

    def test_brief_skips_headlines_that_repeat_a_substantive_sentence(self):
        common = 'AIエージェントを業務に導入するときに知っておきたいこと。'
        sources = [{'title': common + '設計編'}, {'title': common + '運用編'}]
        part = editorial.brief_draft('2026-11-09', sources, 'AIの研究')
        generate.validate_segments(part['segments'])
        editorial.validate_editorial(part, sources, [], 1, 'brief')
        spoken = '\n'.join(s['text'] for s in part['segments'])
        self.assertIn(common + '設計編', spoken)
        self.assertNotIn(common + '運用編', spoken)
        repeated = editorial.brief_draft('2026-11-09',
                                          [{'title': '導入。' + common + common + 'まとめ'}],
                                          'AIの研究')
        editorial.validate_editorial(repeated, [], [], 1, 'brief')
        self.assertIn('読み上げられる見出しを確認できませんでした', repeated['segments'][3]['text'])

    def test_mixed_evidence_reports_only_body_and_audits_complete_news(self):
        headlines = [dict(SOURCE, evidence_status='summary_only', evidence_excerpts=[],
                          title=f'Unknown headline {i}', url=f'https://example.org/headline/{i}')
                     for i in range(7)]
        calls = []
        def fake(prompt, *args, **kwargs):
            if prompt.startswith('EDITORIAL AUDIT'):
                calls.append('audit')
                chapters = json.loads(prompt.split('\n')[-1])
                self.assertEqual([c['role'] for c in chapters], ['report'])
                self.assertEqual(chapters[0]['draft']['story_points'][0]['source_url'], SOURCE['url'])
                self.assertNotIn('Unknown headline', prompt)
                return response({'approved': True, 'issues': []})
            calls.append('report')
            self.assertIn('phonon-1', prompt)
            self.assertNotIn('Unknown headline', prompt)
            return response(report_draft(SOURCE))
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(generate.story_quality, 'collect_evidence', return_value=[SOURCE] + headlines):
            stage = StageCache(folder, '2026-11-09')
            first = self.run_script(fake, stage, evidence=None)
            second = self.run_script(fake, stage, evidence=None)
        self.assertEqual(calls, ['report', 'audit'])
        self.assertEqual(first, second)
        self.assertEqual([s['url'] for s in first[4]], [SOURCE['url']])
        self.assertEqual(len(first[-1]), 1)
        self.assertEqual(first[1]['api_calls'], 2)

    def test_headline_only_fails_before_any_paid_call(self):
        with patch.object(generate.story_quality, 'collect_evidence',
                          return_value=[dict(SOURCE, evidence_status='summary_only')]), \
             patch.object(generate, 'request_gemini') as api:
            with self.assertRaises(ValueError):
                generate.write_script([])
        api.assert_not_called()

    def test_rejects_repeated_opening_and_sentence(self):
        with self.assertRaisesRegex(ValueError, 'opening'):
            editorial.validate_editorial(draft(), [], [], 2, 'brief')
        part = draft(True)
        with self.assertRaisesRegex(ValueError, 'Repeated'):
            editorial.validate_editorial(part, [], [part['segments'][1]], 2, 'practice')

    def test_quoted_greeting_samples_are_not_a_second_opening(self):
        for text in ('対象にする音声サンプルは、「こんにちは」という一言です。',
                     '「おはようございます」を入力して試します。',
                     '読み上げる例文は「『こんばんは』という短い挨拶」です。',
                     '入力例は"こんにちは"です。'):
            part = draft(True)
            part['segments'].insert(1, {'speaker': 'NANA', 'text': text})
            with self.subTest(text=text):
                editorial.validate_editorial(part, [], [], 3, 'practice')

    def test_final_practice_station_signoff_is_allowed(self):
        part = draft(True)
        part['segments'][-1]['text'] = 'それではまた次回。MASURADIO 88.8、NANAがお届けしました。'
        editorial.validate_editorial(part, [], [], 3, 'practice')
        with self.assertRaisesRegex(ValueError, 'marker=station-announcement'):
            editorial.validate_editorial(part, [], [], 2, 'report')

    def test_real_reintroductions_and_unframed_quotes_still_fail(self):
        cases = [
            ('こんにちは、改めて番組を始めましょう。', 'audience-greeting'),
            ('「こんにちは」。今日は音声テストを紹介します。NANAです。', 'audience-greeting'),
            ('入力例は「こんにちは」です。こんばんは、続きをお届けします。', 'audience-greeting'),
            ('入力例は「こんにちは」です。NANAです。', 'host-introduction'),
            ('入力例は「NANAです」です。', 'host-introduction'),
            ('サンプルは「こんにちはという一言です。', 'audience-greeting'),
            ('サンプルは「『こんにちは」です。』', 'audience-greeting'),
            ('「こんにちは」、皆さんにお知らせです。', 'audience-greeting'),
            ('「こんにちは」「サンプル」です。', 'audience-greeting'),
            ('NANAです。実践に進みましょう。', 'host-introduction'),
            ('MASURADIO 88.8をお届けしました。また次回。', 'station-announcement'),
        ]
        for text, marker in cases:
            part = draft(True)
            part['segments'].insert(1, {'speaker': 'NANA', 'text': text})
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, f'marker={marker}'):
                editorial.validate_editorial(part, [], [], 3, 'practice')

    def test_signoff_exception_does_not_hide_greetings_or_host_intro(self):
        for text in ('こんにちは。MASURADIO 88.8、また次回お会いしましょう。',
                     'MASURADIO 88.8、NANAです。また次回お会いしましょう。',
                     'MASURADIO 88.8、次回のテーマを考えてみてください。',
                     'MASURADIO 88.8、入力例は「また次回お会いしましょう」です。'):
            part = draft(True)
            part['segments'][-1]['text'] = text
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'Repeated opening'):
                editorial.validate_editorial(part, [], [], 3, 'practice')

    def test_reintroduction_diagnostics_do_not_expose_draft_content(self):
        part = draft(True)
        part['segments'].insert(2, {'speaker': 'NANA', 'text': 'こんにちは、RAW_DRAFT_PRIVATE_SENTINELです。'})
        with self.assertRaises(ValueError) as raised:
            editorial.validate_editorial(part, [], [], 3, 'practice')
        message = str(raised.exception)
        self.assertIn('chapter=3, segment_index=2, marker=audience-greeting', message)
        self.assertNotIn('RAW_DRAFT_PRIVATE_SENTINEL', message)
        self.assertNotIn('こんにちは', message)

    def test_first_chapter_opening_is_still_allowed(self):
        part = draft()
        part['segments'][0]['text'] = 'こんにちは、MASURADIO 88.8、NANAです。'
        editorial.validate_editorial(part, [], [], 1, 'brief')

    def test_later_chapter_prompt_change_reuses_completed_earlier_chapters(self):
        # A continuation rejection should not replay a completed writing call.
        calls = []
        chapters = [('先の話題', 'report', [SOURCE]), ('次の話題', 'practice', [])]
        failed = False
        def fake(prompt, *args, **kwargs):
            nonlocal failed
            if prompt.startswith('EDITORIAL AUDIT'):
                calls.append('audit')
                return response({'approved': True, 'issues': []})
            if 'This chapter role: practice' in prompt:
                if not failed:
                    failed = True
                    calls.append('later-failed')
                    raise RuntimeError('Later chapter failed')
                calls.append('later-retry')
                return response(draft(True))
            calls.append('report')
            return response(report_draft(SOURCE))
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(editorial, 'plan_chapters', return_value=chapters):
            stage = StageCache(folder, '2026-11-09')
            with self.assertRaisesRegex(RuntimeError, 'Later chapter failed'):
                self.run_script(fake, stage)
            self.run_script(fake, stage)
        self.assertEqual(calls, ['report', 'later-failed', 'later-retry', 'audit'])

    def test_reintroduction_retry_receives_safe_actionable_diagnostics(self):
        calls = []
        chapters = [('先の話題', 'report', [SOURCE]), ('次の話題', 'practice', [])]
        def fake(prompt, *args, **kwargs):
            calls.append(prompt)
            if prompt.startswith('EDITORIAL AUDIT'):
                return response({'approved': True, 'issues': []})
            if 'This chapter role: report' in prompt:
                return response(report_draft(SOURCE))
            part = draft(True)
            if len(calls) == 2:
                part['segments'][-1]['text'] = 'NANAです。また次回お会いしましょう。'
            else:
                self.assertIn('segment_index=5, marker=host-introduction', prompt)
                part['segments'][-1]['text'] = 'MASURADIO 88.8、NANAがお届けしました。また次回。'
            return response(part)
        with patch.object(editorial, 'plan_chapters', return_value=chapters):
            self.run_script(fake)
        self.assertEqual(len(calls), 4)

    def test_exact_quote_and_segment_binding_required(self):
        part = report_draft(SOURCE)
        part['claims'][0]['quote'] = 'invented unsupported attribution'
        with self.assertRaisesRegex(ValueError, 'exact excerpt'):
            editorial.validate_editorial(part, [SOURCE], [], 1, 'report')
        part['claims'][0]['quote'] = SOURCE['evidence_excerpts'][0]['text']
        editorial.validate_editorial(part, [SOURCE], [], 1, 'report')
        part['segments'][1]['text'] = '新しいモデルは利用料が123ドルです。'
        with self.assertRaisesRegex(ValueError, 'number'):
            editorial.validate_editorial(part, [SOURCE], [], 1, 'report')

    def test_reporting_opening_and_metadata_dates_are_not_article_statistics(self):
        part = report_draft(SOURCE)
        part['segments'][0]['text'] = 'こんにちは、MASURADIO 88.8、2026年11月8日の放送です。'
        part['segments'][-1]['text'] = '掲載日は11月6日です。'
        editorial.validate_editorial(part, [SOURCE], [], 1, 'report', '2026-11-08')
        part['segments'][-1]['text'] = '掲載日は11月7日です。'
        with self.assertRaisesRegex(ValueError, 'number'):
            editorial.validate_editorial(part, [SOURCE], [], 1, 'report', '2026-11-08')

    def test_practice_requires_concrete_spoken_steps(self):
        part = draft(True)
        editorial.validate_editorial(part, [], [], 2, 'practice')
        part['practice']['stop'] = '念のため注意しましょう。'
        with self.assertRaisesRegex(ValueError, 'Practice'):
            editorial.validate_editorial(part, [], [], 2, 'practice')

    def run_script(self, fake, stage=None, evidence=True):
        from contextlib import nullcontext
        evidence_patch = patch.object(generate.story_quality, 'collect_evidence', return_value=[SOURCE]) if evidence else nullcontext()
        with evidence_patch, patch.dict(generate.os.environ, {'GEMINI_API_KEY': 'test-only'}), \
             patch.object(generate, 'episode_history', return_value=[]), \
             patch.object(generate, 'request_gemini', side_effect=fake), \
             patch.object(generate.time, 'sleep'):
            return generate.write_script([], stage)

    def test_body_confirmed_chapter_is_not_retold_as_practice(self):
        prompts = []
        def fake(prompt, *args, **kwargs):
            prompts.append(prompt)
            if prompt.startswith('EDITORIAL AUDIT'):
                return response({'approved': True, 'issues': []})
            self.assertIn('phonon-1', prompt)
            return response(report_draft(SOURCE))
        result = self.run_script(fake)
        self.assertEqual(len(prompts), 2)
        self.assertEqual(len(result[-1]), 1)
        self.assertNotIn('evidence_excerpts', result[0][0])

    def test_semantic_audit_rejection_stops_before_audio(self):
        def fake(prompt, *args, **kwargs):
            if prompt.startswith('EDITORIAL AUDIT'):
                self.assertIn('Check every factual statement', prompt)
                return response({'approved': False, 'issues': ['Review dwell time confused with work time']})
            return response(report_draft(SOURCE))
        with self.assertRaisesRegex(RuntimeError, 'Editorial audit rejected'):
            self.run_script(fake)

    def test_audit_fails_closed_for_malformed_or_truncated_response(self):
        for value in (response({'approved': 'true', 'issues': []}),
                      response({'approved': True, 'issues': ['unresolved']}),
                      response({'approved': True, 'issues': []}, finish='MAX_TOKENS')):
            def fake(prompt, *args, **kwargs):
                return value if prompt.startswith('EDITORIAL AUDIT') else response(report_draft(SOURCE))
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                self.run_script(fake)

    def test_completed_audit_and_scripts_are_cached_without_api_calls(self):
        calls = []
        def fake(prompt, *args, **kwargs):
            calls.append(prompt)
            return response({'approved': True, 'issues': []}) if prompt.startswith('EDITORIAL AUDIT') else response(report_draft(SOURCE))
        with tempfile.TemporaryDirectory() as folder:
            stage = StageCache(folder, '2026-11-08')
            first = self.run_script(fake, stage)
            second = self.run_script(fake, stage)
        self.assertEqual(len(calls), 2)
        self.assertEqual(first, second)
        self.assertNotIn('claims', first[0][0])

    def test_editorial_version_invalidates_cached_scripts(self):
        calls = []
        def fake(prompt, *args, **kwargs):
            calls.append(prompt)
            return response({'approved': True, 'issues': []}) if prompt.startswith('EDITORIAL AUDIT') else response(report_draft(SOURCE))
        with tempfile.TemporaryDirectory() as folder:
            stage = StageCache(folder, '2026-11-09')
            self.run_script(fake, stage)
            with patch.object(editorial, 'VERSION', editorial.VERSION + '-next'):
                self.run_script(fake, stage)
        self.assertEqual(len(calls), 4, 'Changed editorial version regenerates writing and audit')

    def test_cached_report_is_validated_before_reuse(self):
        calls = []
        def fake(prompt, *args, **kwargs):
            calls.append(prompt)
            return response({'approved': True, 'issues': []}) if prompt.startswith('EDITORIAL AUDIT') else response(report_draft(SOURCE))
        with tempfile.TemporaryDirectory() as folder:
            stage = StageCache(folder, '2026-11-09')
            first = self.run_script(fake, stage)
            path = next(Path(folder).rglob('script_part_1-*.json'))
            record = json.loads(path.read_text())
            record['value']['story_points'][0]['segment_indices'] = [1]
            record['checksum'] = digest(record['value'])
            path.write_text(json.dumps(record))
            second = self.run_script(fake, stage)
            self.assertEqual(json.loads(path.read_text())['value']['story_points'][0]['segment_indices'], [1, 2])
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 3, 'Invalid cached report is rebuilt; identical audit resumes')

    def test_rejected_audit_is_cached_without_repeated_paid_calls(self):
        calls = []
        def fake(prompt, *args, **kwargs):
            calls.append(prompt)
            return response({'approved': False, 'issues': ['Unsupported attribution']}) if prompt.startswith('EDITORIAL AUDIT') else response(report_draft(SOURCE))
        with tempfile.TemporaryDirectory() as folder:
            stage = StageCache(folder, '2026-11-08')
            for _ in range(2):
                with self.assertRaisesRegex(RuntimeError, 'Editorial audit rejected'):
                    self.run_script(fake, stage)
        self.assertEqual(len(calls), 2)

    def test_invalid_story_points_retry_with_actionable_feedback(self):
        calls = []
        def fake(prompt, *args, **kwargs):
            calls.append(prompt)
            if prompt.startswith('EDITORIAL AUDIT'):
                return response({'approved': True, 'issues': []})
            part = report_draft(SOURCE)
            if len(calls) == 1:
                del part['story_points']
            if len(calls) == 2:
                self.assertIn('Previous draft rejected:', prompt)
            return response(part)
        self.run_script(fake)
        self.assertEqual(len(calls), 3)

    def test_zero_evidence_failure_is_not_cached_and_can_recover(self):
        unknown = dict(SOURCE, evidence_status='summary_only', evidence_excerpts=[],
                       fetch_reason='request_timeout')
        calls = []
        def fake(prompt, *args, **kwargs):
            calls.append(prompt)
            return response({'approved': True, 'issues': []}) if prompt.startswith('EDITORIAL AUDIT') else response(report_draft(SOURCE))
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(generate.story_quality, 'collect_evidence', side_effect=[[unknown], [SOURCE]]) as collect:
            stage = StageCache(folder, '2026-11-09')
            with self.assertRaisesRegex(ValueError, 'No body-confirmed'):
                self.run_script(fake, stage, evidence=None)
            self.assertEqual(calls, [])
            self.assertEqual(list(Path(folder).rglob('article_evidence-*.json')), [])
            result = self.run_script(fake, stage, evidence=None)
            self.assertEqual(collect.call_count, 2)
            self.assertEqual(len(calls), 2)
            self.assertEqual(len(result[4]), 1)

    def test_existing_zero_body_cache_is_invalidated_before_writing(self):
        calls = []
        def fake(prompt, *args, **kwargs):
            calls.append(prompt)
            return response({'approved': True, 'issues': []}) if prompt.startswith('EDITORIAL AUDIT') else response(report_draft(SOURCE))
        with tempfile.TemporaryDirectory() as folder:
            stage = StageCache(folder, '2026-11-09')
            self.run_script(fake, stage)
            path = next(Path(folder).rglob('article_evidence-*.json'))
            record = json.loads(path.read_text())
            record['value'][0]['evidence_status'] = 'summary_only'
            record['value'][0]['evidence_excerpts'] = []
            record['checksum'] = digest(record['value'])
            path.write_text(json.dumps(record))
            with patch.object(generate.story_quality, 'collect_evidence', return_value=[SOURCE]) as collect:
                self.run_script(fake, stage, evidence=None)
                collect.assert_called_once()
            self.assertEqual(len(calls), 2, 'Identical recovered evidence resumes valid scripts and audit')

    def test_empty_feed_snapshot_is_not_cached_and_retries_next_run(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(generate, 'ROOT', Path(folder)), \
             patch.object(generate, 'news', side_effect=[[], [SOURCE]]) as fetch, \
             patch.object(generate, 'write_script', side_effect=RuntimeError('Reached evidence')) as writer:
            with self.assertRaisesRegex(ValueError, 'feed_snapshot: stage validation failed'):
                generate.main()
            writer.assert_not_called()
            self.assertEqual(list(Path(folder).rglob('feed_snapshot-*.json')), [])
            with self.assertRaisesRegex(RuntimeError, 'Reached evidence'):
                generate.main()
            self.assertEqual(fetch.call_count, 2)
            writer.assert_called_once()

    def test_existing_empty_feed_snapshot_is_invalidated(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(generate, 'ROOT', Path(folder)), \
             patch.object(generate, 'news', return_value=[SOURCE]) as fetch, \
             patch.object(generate, 'write_script', side_effect=RuntimeError('Reached evidence')):
            stage = StageCache(Path(folder) / '.radio-cache', generate.TODAY)
            stage.json('feed_snapshot', {'day': generate.TODAY, 'feeds': generate.FEEDS,
                                        'collection_version': 'v1'}, lambda: [])
            with self.assertRaisesRegex(RuntimeError, 'Reached evidence'):
                generate.main()
            fetch.assert_called_once()
