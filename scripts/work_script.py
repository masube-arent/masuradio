"""Bounded import contract for reviewed Work-authored radio scripts.

Review records are maintainer-controlled editorial records, not signatures or
proof of truth. They bind independent source review to the exact submitted JSON.
Only reviewed main-branch packages are used by the production workflow.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit

try:
    from scripts import editorial
except ModuleNotFoundError:
    import editorial

SCHEMA_VERSION = 1
MAX_BYTES = 128_000
REVIEW_CHECKS = frozenset({
    'primary_sources_opened', 'every_spoken_claim_checked',
    'numeric_and_product_scope_checked', 'facts_and_proposals_separated',
    'dx_target_action_check_stop_present', 'public_information_only',
    'no_long_source_copying',
})
PROPOSAL_LABEL = 'ここからは番組の活用提案です。'


def fail(reason):
    raise ValueError('Work script rejected: ' + reason)


def text(value, name, low=1, high=500):
    if not isinstance(value, str) or not low <= len(value.strip()) <= high:
        fail('invalid ' + name)
    return value


def date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        fail('invalid date')
    dt.date.fromisoformat(value)
    return value


def timestamp(value):
    text(value, 'timestamp', high=40)
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        fail('timestamp must include timezone')
    return parsed


def keys(value, required, optional=frozenset()):
    if not isinstance(value, dict) or not required <= set(value) or set(value) - required - optional:
        fail('unexpected or missing fields')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail('duplicate JSON key')
        result[key] = value
    return result


def read_json(path):
    if path.is_symlink() or path.stat().st_size > MAX_BYTES:
        fail('unsafe file or excessive size')
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object,
                      parse_constant=lambda _: fail('non-finite JSON number'))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def source_url(value):
    text(value, 'source URL', high=2048)
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        fail('source URL must be public HTTPS without credentials')
    host = parsed.hostname.lower()
    if ('.' not in host or host.endswith(('.local', '.internal', '.localhost'))
            or not re.search(r'[a-z]', host.rsplit('.', 1)[-1])):
        fail('source URL must be public')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        fail('source URL must name a publisher')
    return value


def validate_source(source):
    keys(source, {'source', 'title', 'url', 'article_published_date', 'retrieved_at',
                  'evidence_status', 'evidence_excerpts'}, {'section_heading'})
    text(source['source'], 'publisher', high=120)
    text(source['title'], 'source title', high=300)
    source_url(source['url'])
    if source['article_published_date'] is not None:
        date(source['article_published_date'])
    timestamp(source['retrieved_at'])
    if 'section_heading' in source:
        text(source['section_heading'], 'section heading', high=300)
    excerpts = source['evidence_excerpts']
    if source['evidence_status'] != 'body' or not isinstance(excerpts, list) or not 1 <= len(excerpts) <= 8:
        fail('body evidence required')
    ids = set()
    for excerpt in excerpts:
        keys(excerpt, {'id', 'text'})
        identifier = text(excerpt['id'], 'excerpt id', high=120)
        text(excerpt['text'], 'excerpt', low=15, high=6000)
        if identifier in ids:
            fail('duplicate excerpt id')
        ids.add(identifier)
    if sum(len(e['text']) for e in excerpts) > 6000:
        fail('excessive evidence')


def validate_package(data, expected_day):
    keys(data, {'schema_version', 'broadcast_date', 'timezone', 'script_id', 'episode_title', 'chapters'})
    if type(data['schema_version']) is not int or data['schema_version'] != SCHEMA_VERSION:
        fail('unsupported schema')
    if date(data['broadcast_date']) != date(expected_day) or data['timezone'] != 'Asia/Tokyo':
        fail('wrong broadcast date or timezone')
    if not isinstance(data['script_id'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', data['script_id']):
        fail('invalid script id')
    text(data['episode_title'], 'episode title', high=120)
    chapters = data['chapters']
    if not isinstance(chapters, list) or not 2 <= len(chapters) <= 4:
        fail('expected reporting and one final DX chapter')
    all_segments, starts, labels, all_sources, drafts, topics = [], [], [], [], [], []
    reported_urls = set()
    for number, chapter in enumerate(chapters, 1):
        keys(chapter, {'title', 'role', 'sources', 'segments', 'claims', 'story_points'}, {'practice'})
        title = text(chapter['title'], 'chapter title', high=120)
        final = number == len(chapters)
        role = chapter['role']
        if role != ('practice' if final else 'report'):
            fail('DX chapter must be last and follow reporting')
        sources = chapter['sources']
        if not isinstance(sources, list) or not 1 <= len(sources) <= 2:
            fail('expected 1-2 sources per chapter')
        local_urls = set()
        for source in sources:
            validate_source(source)
            url = source['url']
            if url in local_urls or (role == 'report' and url in reported_urls):
                fail('repeated reporting source')
            local_urls.add(url)
            if role == 'report':
                reported_urls.add(url)
            if not any(s['url'] == url for s in all_sources):
                all_sources.append(source)
        segments = chapter['segments']
        if not isinstance(segments, list) or not 2 <= len(segments) <= 9:
            fail('expected 2-9 segments per chapter')
        for segment in segments:
            keys(segment, {'speaker', 'text'})
            if segment['speaker'] != 'NANA':
                fail('NANA is the only speaker')
            text(segment['text'], 'speech', low=5, high=500)
            if re.search(r'https?://|```', segment['text']):
                fail('speech must not contain URLs or code blocks')
        if not isinstance(chapter['claims'], list) or len(chapter['claims']) > 64:
            fail('invalid claims')
        for claim in chapter['claims']:
            keys(claim, {'segment_index', 'excerpt_id'})
        if not isinstance(chapter['story_points'], list):
            fail('invalid story coverage')
        if role == 'practice':
            if chapter['story_points'] or PROPOSAL_LABEL not in ''.join(s['text'] for s in segments[:2]):
                fail('DX proposals must be explicitly introduced')
            keys(chapter.get('practice'), {'target', 'action', 'check', 'stop'})
            for value in chapter['practice'].values():
                text(value, 'DX criterion', low=8, high=500)
        elif 'practice' in chapter:
            fail('reporting cannot masquerade as a proposal')
        bound = editorial.bind_claims(chapter, sources)
        editorial.validate_editorial(bound, sources, all_segments, number, role, expected_day,
                                     final_chapter=final)
        # Source-backed factual DX segments retain report-level numeric support.
        # Proposal-only steps are reviewed editorially and are never claims of results.
        if role == 'practice':
            for index, segment in enumerate(segments):
                claims = [c for c in bound['claims'] if c['segment_index'] == index]
                if claims:
                    supported = set(re.findall(r'\d+(?:[.,]\d+)*', unicodedata.normalize('NFKC', ' '.join(c['quote'] for c in claims))))
                    spoken = re.findall(r'\d+(?:[.,]\d+)*', unicodedata.normalize('NFKC', segment['text']))
                    if any(n not in supported for n in spoken):
                        fail('unsupported factual DX number')
        starts.append(len(all_segments))
        labels.append(title)
        all_segments.extend(segments)
        drafts.append(bound)
        topics.append((title, role, sources))
    if len(reported_urls) > 5:
        fail('too many reporting stories')
    return {'segments': all_segments, 'starts': starts, 'labels': labels,
            'sources': all_sources, 'drafts': drafts, 'topics': topics,
            'script_hash': digest(data), 'data': data}


def validate_review(review, script_hash):
    keys(review, {'schema_version', 'script_sha256', 'reviewed_at', 'reviewer', 'decision', 'checks', 'issues'})
    if type(review['schema_version']) is not int or review['schema_version'] != 1:
        fail('unsupported review schema')
    if review['script_sha256'] != script_hash or review['decision'] != 'approved' or review['issues'] != []:
        fail('missing, rejected, or stale editorial review')
    if review['reviewer'] != 'independent-work-review':
        fail('independent review required')
    timestamp(review['reviewed_at'])
    if not isinstance(review['checks'], list) or any(not isinstance(x, str) for x in review['checks']):
        fail('invalid review checklist')
    if len(review['checks']) != len(REVIEW_CHECKS) or set(review['checks']) != REVIEW_CHECKS:
        fail('incomplete review checklist')
    return review


def load_submission(root, day, require_review=True):
    date(day)
    directory = Path(root).resolve() / 'drafts' / day
    if directory.resolve() != directory:
        fail('symlinked draft directory')
    data = read_json(directory / 'script.json')
    prepared = validate_package(data, day)
    if require_review:
        prepared['review'] = validate_review(read_json(directory / 'review.json'), prepared['script_hash'])
    return prepared


def validate_all(root):
    paths = sorted((Path(root) / 'drafts').glob('*/script.json'))
    if not paths:
        fail('no submitted scripts')
    for path in paths:
        prepared = load_submission(root, path.parent.name)
        print('Reviewed Work script valid:', path.parent.name, prepared['script_hash'][:12])


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--date')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.all:
        validate_all(root)
    elif args.date:
        prepared = load_submission(root, args.date)
        print('Reviewed Work script valid:', args.date, prepared['script_hash'][:12])
    else:
        parser.error('provide --all or --date')
