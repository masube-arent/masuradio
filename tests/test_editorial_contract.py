import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import editorial, generate
from scripts.stage_resume import StageCache, digest
from editorial_fixtures import draft, response


SOURCE = {'source': 'Hugging Face', 'title': 'Phonon', 'url': 'https://example.org/phonon',
          'date': '2026-11-07', 'article_published_date': '2026-11-06',
          'evidence_status': 'body', 'evidence_excerpts': [
              {'id': 'phonon-1', 'text': 'Phonon is developed by Gradium and presented on Hugging Face.'},
              {'id': 'review-1', 'text': 'Review-stage dwell time increased by 441% compared with the baseline.'}]}


class EditorialContractTests(unittest.TestCase):
    def test_reporting_allocations_are_disjoint_and_practice_has_evidence(self):
        sources = [dict(SOURCE, url=f'https://example.org/{i}') for i in range(5)]
        chapters = editorial.plan_chapters(sources)
        reported = [s['url'] for _, role, group in chapters if role != 'practice' for s in group]
        self.assertEqual(len(reported), len(set(reported)))
        self.assertEqual(chapters[-1][2], sources[:1])

    def test_prompt_preserves_prior_script_dates_and_attribution_rules(self):
        chapters = editorial.plan_chapters([SOURCE])
        prompt = editorial.chapter_prompt('2026-11-08', 2, chapters, 'focus', 'direction', [], draft()['segments'])
        for expected in ('441%', 'Gradium', 'reviewer work time', '2026-11-06', 'feed_date',
                         'License', 'Japanese', draft()['segments'][1]['text']):
            self.assertIn(expected, prompt)
        self.assertIn('not a 441% reduction', prompt)

    def test_unknown_body_does_not_authorize_reporting(self):
        chapters = editorial.plan_chapters([dict(SOURCE, evidence_status='summary_only')])
        self.assertNotIn('report', [c[1] for c in chapters])
        self.assertEqual(chapters[-1][2], [])
        self.assertEqual(editorial.source_evidence(chapters[0][2])[0]['excerpts'], [])

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

    def test_mixed_evidence_uses_fixed_brief_and_audits_all_chapters(self):
        headlines = [dict(SOURCE, evidence_status='summary_only', evidence_excerpts=[],
                          title=title, url=f'https://example.org/headline/{i}')
                     for i, title in enumerate([
                         'Audio codec research', 'Medical imaging assistant', 'Education lesson planner',
                         'Robotics walking demo', 'Database privacy controls',
                         'Weather prediction update', 'Compiler optimization release'])]
        calls = []
        def fake(prompt, *args, **kwargs):
            self.assertNotIn('This chapter role: brief', prompt)
            if prompt.startswith('EDITORIAL AUDIT'):
                calls.append('audit')
                chapters = json.loads(prompt.split('\n')[-1])
                self.assertEqual([c['role'] for c in chapters], ['brief', 'report', 'practice'])
                self.assertEqual(chapters[0]['draft']['claims'], [])
                self.assertTrue(all(v == 0 for v in chapters[0]['draft']['usage'].values()))
                self.assertIn('未確認の見出しとして', chapters[0]['draft']['segments'][3]['text'])
                self.assertEqual(chapters[0]['evidence'][0]['excerpts'], [])
                return response({'approved': True, 'issues': []})
            self.assertIn('phonon-1', prompt)
            if 'This chapter role: practice' in prompt:
                calls.append('practice')
                return response(draft(True))
            calls.append('report')
            part = draft()
            part['segments'][0]['text'] = 'ここからは記事本文を確認できた話題です。'
            part['segments'][1]['text'] = '掲載日は11月6日です。'
            part['segments'][2]['text'] = 'Phononの開発元はGradiumと記事で説明されています。'
            part['claims'] = [{'segment_index': 2, 'excerpt_id': 'phonon-1',
                               'quote': SOURCE['evidence_excerpts'][0]['text']}]
            return response(part)
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(generate.story_quality, 'collect_evidence', return_value=[SOURCE] + headlines):
            stage = StageCache(folder, '2026-11-09')
            first = self.run_script(fake, stage)
            second = self.run_script(fake, stage)
        self.assertEqual(calls, ['report', 'practice', 'audit'])
        self.assertEqual(first, second)
        self.assertEqual(len(first[4]), 8)
        self.assertEqual(first[-1], ['ニュース', '根拠と深掘り', '実践・まとめ'])
        self.assertEqual(first[1]['api_calls'], 3)

    def test_headline_only_does_not_call_writer_for_brief(self):
        calls = []
        def fake(prompt, *args, **kwargs):
            self.assertNotIn('This chapter role: brief', prompt)
            calls.append('audit' if prompt.startswith('EDITORIAL AUDIT') else 'practice')
            return response({'approved': True, 'issues': []}) if calls[-1] == 'audit' else response(draft(True))
        with patch.object(generate.story_quality, 'collect_evidence',
                          return_value=[dict(SOURCE, evidence_status='summary_only')]):
            result = self.run_script(fake)
        self.assertEqual(calls, ['practice', 'audit'])
        self.assertEqual(result[-1], ['ニュース', '実践・まとめ'])

    def test_rejects_repeated_opening_and_sentence(self):
        with self.assertRaisesRegex(ValueError, 'opening'):
            editorial.validate_editorial(draft(), [], [], 2, 'brief')
        part = draft(True)
        with self.assertRaisesRegex(ValueError, 'Repeated'):
            editorial.validate_editorial(part, [], [part['segments'][1]], 2, 'practice')

    def test_exact_quote_and_segment_binding_required(self):
        part = draft()
        part['claims'] = [{'segment_index': 2, 'excerpt_id': 'phonon-1', 'quote': 'invented unsupported attribution'}]
        with self.assertRaisesRegex(ValueError, 'exact excerpt'):
            editorial.validate_editorial(part, [SOURCE], [], 1, 'report')
        part['claims'][0]['quote'] = SOURCE['evidence_excerpts'][0]['text']
        editorial.validate_editorial(part, [SOURCE], [], 1, 'report')
        part['segments'][2]['text'] = '新しいモデルは利用料が123ドルです。'
        with self.assertRaisesRegex(ValueError, 'number'):
            editorial.validate_editorial(part, [SOURCE], [], 1, 'report')

    def test_reporting_opening_and_metadata_dates_are_not_article_statistics(self):
        part = draft()
        part['segments'][0]['text'] = 'こんにちは、MASURADIO 88.8、2026年11月8日の放送です。'
        part['segments'][1]['text'] = '掲載日は11月6日です。'
        part['claims'] = [{'segment_index': 2, 'excerpt_id': 'phonon-1',
                           'quote': SOURCE['evidence_excerpts'][0]['text']}]
        editorial.validate_editorial(part, [SOURCE], [], 1, 'report', '2026-11-08')
        part['segments'][1]['text'] = '掲載日は11月7日です。'
        with self.assertRaisesRegex(ValueError, 'number'):
            editorial.validate_editorial(part, [SOURCE], [], 1, 'report', '2026-11-08')

    def test_practice_requires_concrete_spoken_steps(self):
        part = draft(True)
        editorial.validate_editorial(part, [], [], 2, 'practice')
        part['practice']['stop'] = '念のため注意しましょう。'
        with self.assertRaisesRegex(ValueError, 'Practice'):
            editorial.validate_editorial(part, [], [], 2, 'practice')

    def run_script(self, fake, stage=None):
        with patch.dict(generate.os.environ, {'GEMINI_API_KEY': 'test-only'}), \
             patch.object(generate, 'episode_history', return_value=[]), \
             patch.object(generate, 'request_gemini', side_effect=fake), \
             patch.object(generate.time, 'sleep'):
            return generate.write_script([], stage)

    def test_body_confirmed_first_chapter_and_practice_share_evidence(self):
        prompts = []
        def fake(prompt, *args, **kwargs):
            prompts.append(prompt)
            if prompt.startswith('EDITORIAL AUDIT'):
                return response({'approved': True, 'issues': []})
            if 'This chapter role: practice' in prompt:
                self.assertIn('phonon-1', prompt)
                self.assertIn('Gradium', prompt)
                return response(draft(True))
            part = draft()
            part['segments'][0]['text'] = 'こんにちは、MASURADIO 88.8です。'
            part['segments'][1]['text'] = '掲載日は11月6日です。'
            part['segments'][2]['text'] = 'Phononの開発元はGradiumと記事で説明されています。'
            part['claims'] = [{'segment_index': 2, 'excerpt_id': 'phonon-1',
                               'quote': SOURCE['evidence_excerpts'][0]['text']}]
            return response(part)
        with patch.object(generate.story_quality, 'collect_evidence', return_value=[SOURCE]):
            result = self.run_script(fake)
        self.assertEqual(len(prompts), 3)
        self.assertEqual(result[-1], ['根拠と深掘り', '実践・まとめ'])
        self.assertNotIn('evidence_excerpts', result[0][0])

    def test_semantic_audit_rejection_stops_before_audio(self):
        def fake(prompt, *args, **kwargs):
            if prompt.startswith('EDITORIAL AUDIT'):
                self.assertIn('Check every factual statement', prompt)
                return response({'approved': False, 'issues': ['Review dwell time confused with work time']})
            return response(draft('This chapter role: practice' in prompt))
        with self.assertRaisesRegex(RuntimeError, 'Editorial audit rejected'):
            self.run_script(fake)

    def test_audit_fails_closed_for_malformed_or_truncated_response(self):
        for value in (response({'approved': 'true', 'issues': []}),
                      response({'approved': True, 'issues': ['unresolved']}),
                      response({'approved': True, 'issues': []}, finish='MAX_TOKENS')):
            def fake(prompt, *args, **kwargs):
                return value if prompt.startswith('EDITORIAL AUDIT') else response(draft('This chapter role: practice' in prompt))
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                self.run_script(fake)

    def test_completed_audit_and_scripts_are_cached_without_api_calls(self):
        calls = []
        def fake(prompt, *args, **kwargs):
            calls.append(prompt)
            return response({'approved': True, 'issues': []}) if prompt.startswith('EDITORIAL AUDIT') else response(draft('This chapter role: practice' in prompt))
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
            return response({'approved': True, 'issues': []}) if prompt.startswith('EDITORIAL AUDIT') else response(draft(True))
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(editorial, 'brief_draft', wraps=editorial.brief_draft) as brief:
            stage = StageCache(folder, '2026-11-09')
            self.run_script(fake, stage)
            with patch.object(editorial, 'VERSION', editorial.VERSION + '-next'):
                self.run_script(fake, stage)
        self.assertEqual(brief.call_count, 2)
        self.assertEqual(len(calls), 4, 'Practice and audit must be rerun for a new editorial version')

    def test_cached_brief_is_validated_before_reuse(self):
        calls = []
        def fake(prompt, *args, **kwargs):
            calls.append(prompt)
            return response({'approved': True, 'issues': []}) if prompt.startswith('EDITORIAL AUDIT') else response(draft(True))
        with tempfile.TemporaryDirectory() as folder:
            stage = StageCache(folder, '2026-11-09')
            first = self.run_script(fake, stage)
            path = next(Path(folder).rglob('script_part_1-*.json'))
            record = json.loads(path.read_text())
            record['value']['claims'] = [{'segment_index': 0, 'excerpt_id': 'invented',
                                         'quote': 'This is not body evidence.'}]
            record['checksum'] = digest(record['value'])
            path.write_text(json.dumps(record))
            with patch.object(editorial, 'brief_draft', wraps=editorial.brief_draft) as brief:
                second = self.run_script(fake, stage)
            self.assertEqual(brief.call_count, 1)
            self.assertEqual(json.loads(path.read_text())['value']['claims'], [])
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 2, 'Rebuilding the same brief must not repeat paid calls')

    def test_rejected_audit_is_cached_without_repeated_paid_calls(self):
        calls = []
        def fake(prompt, *args, **kwargs):
            calls.append(prompt)
            return response({'approved': False, 'issues': ['Unsupported attribution']}) if prompt.startswith('EDITORIAL AUDIT') else response(draft('This chapter role: practice' in prompt))
        with tempfile.TemporaryDirectory() as folder:
            stage = StageCache(folder, '2026-11-08')
            for _ in range(2):
                with self.assertRaisesRegex(RuntimeError, 'Editorial audit rejected'):
                    self.run_script(fake, stage)
        self.assertEqual(len(calls), 2)

    def test_invalid_practice_retries_with_actionable_feedback(self):
        calls = []
        def fake(prompt, *args, **kwargs):
            calls.append(prompt)
            if prompt.startswith('EDITORIAL AUDIT'):
                return response({'approved': True, 'issues': []})
            part = draft('This chapter role: practice' in prompt)
            if len(calls) == 1:
                del part['practice']
            if len(calls) == 2:
                self.assertIn('Previous draft rejected: Practice', prompt)
            return response(part)
        self.run_script(fake)
        self.assertEqual(len(calls), 3)
