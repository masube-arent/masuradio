import tempfile
import unittest
from unittest.mock import patch
from scripts import editorial, generate
from scripts.stage_resume import StageCache
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
        self.assertEqual(len(calls), 3)
        self.assertEqual(first, second)
        self.assertNotIn('claims', first[0][0])

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
        self.assertEqual(len(calls), 3)

    def test_invalid_practice_retries_with_actionable_feedback(self):
        calls = []
        def fake(prompt, *args, **kwargs):
            calls.append(prompt)
            if prompt.startswith('EDITORIAL AUDIT'):
                return response({'approved': True, 'issues': []})
            part = draft('This chapter role: practice' in prompt)
            if len(calls) == 2:
                del part['practice']
            if len(calls) == 3:
                self.assertIn('Previous draft rejected: Practice', prompt)
            return response(part)
        self.run_script(fake)
        self.assertEqual(len(calls), 4)
