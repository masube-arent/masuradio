"""Offline acceptance, rejection, review binding, and publication safety."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import publish_work, work_script

DAY = '2026-11-10'


def package():
    source = {'source': 'Example publisher', 'title': 'Fixture announcement',
              'url': 'https://example.com/news', 'article_published_date': DAY,
              'retrieved_at': '2026-11-10T00:00:00Z', 'evidence_status': 'body',
              'evidence_excerpts': [{'id': 'facts', 'text': 'The tool groups settings and lets users search every setting.'}]}
    return {'schema_version': 1, 'broadcast_date': DAY, 'timezone': 'Asia/Tokyo',
            'script_id': 'fixture-1', 'episode_title': '設定管理のニュースと活用提案',
            'chapters': [
                {'title': '設定管理のニュース', 'role': 'report', 'sources': [source],
                 'segments': [{'speaker': 'NANA', 'text': '設定をまとめて管理できる機能が案内されました。'},
                              {'speaker': 'NANA', 'text': '設定全体を検索する機能も利用できます。'}],
                 'claims': [{'segment_index': 0, 'excerpt_id': 'S1E1'}, {'segment_index': 1, 'excerpt_id': 'S1E1'}],
                 'story_points': [{'source_url': source['url'], 'segment_indices': [0, 1]}]},
                {'title': '今日のDXハック', 'role': 'practice', 'sources': [copy.deepcopy(source)],
                 'segments': [{'speaker': 'NANA', 'text': work_script.PROPOSAL_LABEL + '対象は公開の練習用設定です。手順は設定名を検索することです。'},
                              {'speaker': 'NANA', 'text': '確認するのは元の設定との一致です。機密情報が見えたら作業を止めます。'}],
                 'claims': [], 'story_points': [],
                 'practice': {'target': '対象は公開の練習用設定です。', 'action': '手順は設定名を検索することです。',
                              'check': '確認するのは元の設定との一致です。', 'stop': '機密情報が見えたら作業を止めます。'}}]}


def review(data):
    return {'schema_version': 1, 'script_sha256': work_script.digest(data),
            'reviewed_at': '2026-11-10T01:00:00Z', 'reviewer': 'independent-work-review',
            'decision': 'approved', 'checks': sorted(work_script.REVIEW_CHECKS), 'issues': []}


def submission(root, data=None):
    data = data or package()
    folder = root / 'drafts' / DAY
    folder.mkdir(parents=True)
    (folder / 'script.json').write_text(json.dumps(data), encoding='utf-8')
    (folder / 'review.json').write_text(json.dumps(review(data)), encoding='utf-8')
    return folder


class WorkScriptTests(unittest.TestCase):
    def reject(self, mutate):
        data = package()
        mutate(data)
        with self.assertRaises((ValueError, TypeError, KeyError)):
            work_script.validate_package(data, DAY)

    def test_valid_reports_and_dx(self):
        result = work_script.validate_package(package(), DAY)
        self.assertEqual(result['starts'], [0, 2])
        self.assertEqual(len(result['sources']), 1)
        self.assertEqual(len(result['segments']), 4)

    def test_hash_stable_across_json_key_order(self):
        data = package()
        self.assertEqual(work_script.digest(data), work_script.digest(dict(reversed(list(data.items())))))

    def test_hash_changes_with_speech_and_evidence(self):
        original = package(); changed = copy.deepcopy(original)
        changed['chapters'][0]['segments'][0]['text'] += '変更です。'
        self.assertNotEqual(work_script.digest(original), work_script.digest(changed))
        changed = copy.deepcopy(original)
        changed['chapters'][0]['sources'][0]['evidence_excerpts'][0]['text'] += ' Changed.'
        self.assertNotEqual(work_script.digest(original), work_script.digest(changed))

    def test_schema_boolean(self): self.reject(lambda x: x.update(schema_version=True))
    def test_unknown_approval_field(self): self.reject(lambda x: x.update(approved=True))
    def test_wrong_day(self): self.reject(lambda x: x.update(broadcast_date='2026-11-11'))
    def test_impossible_date(self): self.reject(lambda x: x.update(broadcast_date='2026-02-30'))
    def test_wrong_timezone(self): self.reject(lambda x: x.update(timezone='UTC'))
    def test_path_script_id(self): self.reject(lambda x: x.update(script_id='../escape'))
    def test_no_dx(self): self.reject(lambda x: x['chapters'].pop())
    def test_missing_dx_label(self): self.reject(lambda x: x['chapters'][1]['segments'][0].update(text='公開の練習用設定を使います。'))
    def test_missing_dx_stop(self): self.reject(lambda x: x['chapters'][1]['practice'].pop('stop'))
    def test_dx_criterion_not_spoken(self): self.reject(lambda x: x['chapters'][1]['practice'].update(stop='画面を閉じて管理者へ連絡します。'))
    def test_wrong_voice(self): self.reject(lambda x: x['chapters'][0]['segments'][0].update(speaker='OTHER'))
    def test_empty_speech(self): self.reject(lambda x: x['chapters'][0]['segments'][0].update(text=''))
    def test_oversized_speech(self): self.reject(lambda x: x['chapters'][0]['segments'][0].update(text='あ'*501))
    def test_speech_url(self): self.reject(lambda x: x['chapters'][0]['segments'][0].update(text='https://example.com を参照します。'))
    def test_no_body_evidence(self): self.reject(lambda x: x['chapters'][0]['sources'][0].update(evidence_status='summary_only'))
    def test_missing_claims(self): self.reject(lambda x: x['chapters'][0].update(claims=[]))
    def test_unknown_excerpt(self): self.reject(lambda x: x['chapters'][0]['claims'][0].update(excerpt_id='S1E99'))
    def test_claim_boolean_index(self): self.reject(lambda x: x['chapters'][0]['claims'][0].update(segment_index=True))
    def test_foreign_source_claim(self): self.reject(lambda x: x['chapters'][0]['claims'][0].update(source_url='https://other.example.com/'))
    def test_unsupported_number(self): self.reject(lambda x: x['chapters'][0]['segments'][0].update(text='作業時間が99%短縮されました。'))
    def test_title_only_number(self):
        def mutate(x):
            x['chapters'][0]['sources'][0]['title'] = 'Release 99'
            x['chapters'][0]['segments'][0]['text'] = 'バージョン99が公開されました。'
        self.reject(mutate)
    def test_single_fact_coverage(self): self.reject(lambda x: x['chapters'][0]['story_points'][0].update(segment_indices=[0]))
    def test_duplicate_speech(self): self.reject(lambda x: x['chapters'][0]['segments'].__setitem__(1, copy.deepcopy(x['chapters'][0]['segments'][0])))
    def test_duplicate_source(self): self.reject(lambda x: x['chapters'][0]['sources'].append(copy.deepcopy(x['chapters'][0]['sources'][0])))
    def test_http_source(self): self.reject(lambda x: x['chapters'][0]['sources'][0].update(url='http://example.com/'))
    def test_source_credentials(self): self.reject(lambda x: x['chapters'][0]['sources'][0].update(url='https://user:password@example.com/'))
    def test_ip_source(self): self.reject(lambda x: x['chapters'][0]['sources'][0].update(url='https://127.0.0.1/'))
    def test_shorthand_ip_source(self): self.reject(lambda x: x['chapters'][0]['sources'][0].update(url='https://127.1/'))
    def test_local_source(self): self.reject(lambda x: x['chapters'][0]['sources'][0].update(url='https://intranet.local/'))
    def test_unknown_source_field(self): self.reject(lambda x: x['chapters'][0]['sources'][0].update(command='not executed'))
    def test_duplicate_excerpt(self): self.reject(lambda x: x['chapters'][0]['sources'][0]['evidence_excerpts'].append(copy.deepcopy(x['chapters'][0]['sources'][0]['evidence_excerpts'][0])))

    def test_review_bound_to_exact_script(self):
        record = review(package())
        work_script.validate_review(record, record['script_sha256'])
        with self.assertRaises(ValueError): work_script.validate_review(record, '0'*64)

    def test_review_rejection_and_missing_checks_fail(self):
        for field, value in [('decision', 'rejected'), ('issues', ['unsupported fact']), ('checks', []), ('reviewer', 'writer')]:
            record = review(package()); record[field] = value
            with self.assertRaises(ValueError): work_script.validate_review(record, work_script.digest(package()))

    def test_duplicate_json_key_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'duplicate.json'; path.write_text('{"x":1,"x":2}')
            with self.assertRaises(ValueError): work_script.read_json(path)

    def test_nonfinite_json_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'nan.json'; path.write_text('{"x":NaN}')
            with self.assertRaises(ValueError): work_script.read_json(path)

    def test_size_limit_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'input.json'; path.write_text(' '* (work_script.MAX_BYTES+1))
            with self.assertRaises(ValueError): work_script.read_json(path)
            link=Path(tmp)/'link.json'; link.symlink_to(path)
            with self.assertRaises(ValueError): work_script.read_json(link)

    def test_load_submission_and_stale_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); folder=submission(root)
            prepared=work_script.load_submission(root, DAY)
            self.assertEqual(prepared['script_hash'], work_script.digest(package()))
            changed=package(); changed['episode_title']='変更した題名'
            (folder/'script.json').write_text(json.dumps(changed))
            with self.assertRaises(ValueError): work_script.load_submission(root, DAY)

    def test_missing_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=submission(Path(tmp)); (folder/'review.json').unlink()
            with self.assertRaises(FileNotFoundError): work_script.load_submission(Path(tmp), DAY)

    def test_production_workflow_has_no_paid_fallback(self):
        text=(Path(__file__).resolve().parents[1]/'.github/workflows/daily.yml').read_text()
        self.assertIn('python scripts/publish_work.py', text)
        self.assertNotIn('GEMINI_API_KEY:', text)
        self.assertNotIn('python scripts/generate.py', text)
        self.assertIn('drafts/**', text)
        self.assertIn('cancel-in-progress: false', text)


class WorkPublicationTests(unittest.TestCase):
    def test_archive_preserves_work_provenance_for_player(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'scripts').mkdir(); (root/'episodes').mkdir()
            source = Path(__file__).resolve().parents[1]/'scripts/build_index.py'
            target = root/'scripts/build_index.py'; target.write_text(source.read_text())
            data = {'date': DAY, 'title': 'Reviewed broadcast', 'duration_seconds': 60,
                    'audio': f'episodes/{DAY}.mp3', 'production_method': 'work-researched-script',
                    'script_hash': 'verified-hash'}
            (root/'episodes'/f'{DAY}.json').write_text(json.dumps(data))
            (root/'episodes'/f'{DAY}.mp3').write_bytes(b'fixture')
            subprocess.run([sys.executable, str(target)], check=True)
            index = json.loads((root/'episodes/index.json').read_text())
            self.assertEqual(index[0]['production_method'], 'work-researched-script')
            self.assertEqual(index[0]['script_hash'], 'verified-hash')

    def test_undecodable_old_audio_can_recover_without_touching_until_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); submission(root); out=root/'episodes'; out.mkdir()
            (out/f'{DAY}.json').write_text('old json'); (out/f'{DAY}.mp3').write_bytes(b'old corrupt audio')
            async def failed(*args, **kwargs): raise RuntimeError('render reached')
            with patch.object(publish_work.verify, 'check_episode', side_effect=subprocess.CalledProcessError(1, 'ffprobe')), \
                 patch.object(publish_work.generate, 'render', side_effect=failed):
                with self.assertRaisesRegex(RuntimeError, 'render reached'):
                    publish_work.publish(root, DAY)
            self.assertEqual((out/f'{DAY}.mp3').read_bytes(), b'old corrupt audio')

    def test_valid_existing_script_skips_all_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); submission(root); (root/'episodes').mkdir()
            (root/'episodes'/f'{DAY}.json').write_text('{}')
            old={'script_hash': work_script.digest(package()), 'duration_seconds': 60}
            with patch.object(publish_work.verify, 'check_episode', return_value=old), \
                 patch.object(publish_work.generate, 'render', side_effect=AssertionError('TTS called')), \
                 patch.object(publish_work.generate, 'request_gemini', side_effect=AssertionError('Gemini called')):
                self.assertEqual(publish_work.publish(root, DAY), old)

    def test_different_existing_script_requires_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); submission(root); (root/'episodes').mkdir()
            (root/'episodes'/f'{DAY}.json').write_text('{}')
            with patch.object(publish_work.verify, 'check_episode', return_value={'script_hash':'another'}), \
                 patch.object(publish_work.generate, 'render', side_effect=AssertionError('TTS called')):
                with self.assertRaisesRegex(ValueError, 'explicit replacement'):
                    publish_work.publish(root, DAY)

    def test_failed_tts_does_not_touch_old_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); submission(root); out=root/'episodes'; out.mkdir()
            (out/f'{DAY}.json').write_text('old json'); (out/f'{DAY}.mp3').write_bytes(b'old audio')
            async def failed(*args, **kwargs): raise RuntimeError('TTS unavailable')
            with patch.object(publish_work.verify, 'check_episode', return_value={'script_hash':'old'}), \
                 patch.object(publish_work.generate, 'render', side_effect=failed):
                with self.assertRaisesRegex(RuntimeError, 'TTS unavailable'):
                    publish_work.publish(root, DAY, replace_existing=True)
            self.assertEqual((out/f'{DAY}.json').read_text(), 'old json')
            self.assertEqual((out/f'{DAY}.mp3').read_bytes(), b'old audio')

    def test_missing_input_stops_before_tts(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(publish_work.generate, 'render', side_effect=AssertionError('TTS called')):
            with self.assertRaises(FileNotFoundError): publish_work.publish(Path(tmp), DAY)


if __name__ == '__main__': unittest.main()
