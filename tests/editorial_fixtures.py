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
