"""Small valid offline drafts, intentionally distinct across chapters."""
import json


def draft(practice=False):
    texts = ([
        'ここからは私の提案する、出典を確かめる練習です。',
        '対象は手元にある記事の見出しと、その出典リンクです。',
        '行動は本文を開いて、主張を裏付ける一文を探すことです。',
        '成功条件はその一文と見出しの意味が一致することです。',
        '中止条件は本文が読めないか、根拠が見つからないことです。',
        'それではまた次回、気になった情報を確かめてみましょう。',
    ] if practice else [
        'こんにちは、今日も気になる情報を一緒に見ていきましょう。',
        '今回は記事本文を確認できる資料がありませんでした。',
        '詳しい発表内容の紹介は、確認できるまで見送ります。',
        '情報がないところを想像で埋めないことも大切ですね。',
        '気になる見出しでも、詳しい説明とは分けて受け止めたいです。',
        'この後は、出典を確かめる練習に進みましょう。',
    ])
    result = {'segments': [{'speaker': 'NANA', 'text': t} for t in texts], 'claims': []}
    if practice:
        result['practice'] = dict(zip(('target', 'action', 'check', 'stop'), texts[1:5]))
    return result


def response(payload, finish='STOP'):
    return {'usageMetadata': {}, 'candidates': [{'finishReason': finish,
            'content': {'parts': [{'text': json.dumps(payload, ensure_ascii=False)}]}}]}


SOURCE = {'source': 'Example Research', 'title': 'Phonon research update',
          'url': 'https://example.org/phonon', 'date': '2026-11-07',
          'article_published_date': '2026-11-06', 'evidence_status': 'body',
          'evidence_excerpts': [
              {'id': 'phonon-1', 'text': 'Phonon is developed by Gradium and presented on Hugging Face.'},
              {'id': 'review-1', 'text': 'Review-stage dwell time increased by 441% compared with the baseline.'}]}


def report_draft(source=None):
    source = source or SOURCE
    excerpts = source['evidence_excerpts'][:2]
    texts = ['こんにちは、記事の新しい内容をお伝えします。'] + [e['text'] for e in excerpts]
    texts.append('短いニュースをお聞きいただきありがとうございました。')
    return {'segments': [{'speaker': 'NANA', 'text': t} for t in texts],
            'claims': [{'segment_index': i + 1, 'excerpt_id': e['id'], 'quote': e['text']}
                       for i, e in enumerate(excerpts)],
            'story_points': [{'source_url': source['url'], 'segment_indices': [1, 2]}],
            'episode_title': '研究発表の新しい内容と確認した条件'}
