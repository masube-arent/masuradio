"""Bounded, respectful evidence gathering and conservative multi-source deduplication.

Article snippets are strictly transient generation input: never serialize excerpts to
public episode metadata. No credentials, login, paywall bypass or paid AI calls.
"""
from __future__ import annotations

import datetime as dt
import html
import ipaddress
import re
import unicodedata
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit, urljoin
from urllib.robotparser import RobotFileParser

import requests

USER_AGENT = 'MASURADIO-evidence/1.0 (+public RSS digest)'
TRACKING = {'fbclid', 'gclid', 'dclid', 'mc_cid', 'mc_eid', 'igshid',
            'ref_src', 'ref_url', 'vero_id', 'yclid'}
MAX_ARTICLES = 7
MAX_BYTES = 240_000
MIN_BODY_CHARS = 200
MAX_EXCERPTS = 5
ENTITY_ALIASES = {
    'claude code': r'claude[\s\-]*code|クロードコード',
    'github copilot': r'(?:github[\s\-]*)?copilot|コパイロット',
    'gemini': r'gemini|ジェミニ',
    'chatgpt': r'chat\s*gpt|チャットジーピーティー',
    'codex': r'codex|コーデックス',
    'deepmind': r'deepmind|ディープマインド',
    'openai': r'openai|オープンエーアイ',
    'hugging face': r'hugging\s*face',
}
ACTION_ALIASES = {
    'release': r'release|launch|introduc|unveil|roll.?out|publish|announc|発表|公開|提供|リリース|導入',
    'price': r'pricing|price|cost|budget|bill|料金|価格|値下げ|値上げ',
    'security': r'secur|vulnerab|privacy|attack|hack|保護|脆弱性|セキュリティ',
    'research': r'research|paper|benchmar|experiment|研究|論文|ベンチマーク',
    'partnership': r'partner|collaborat|acquir|merger|提携|買収|協業',
}
STOPWORDS = {'the', 'a', 'an', 'is', 'in', 'for', 'on', 'of', 'to', 'and', 'with',
             'by', 'at', 'as', 'from', 'new', 'latest', 'how', 'using', 'update',
             'updates', 'announces', 'introduces', 'launches', 'releases', 'release',
             'google', 'openai', 'microsoft', 'github', 'anthropic'}


def normalize_url(url: str) -> str:
    """Remove trackers/fragments, preserve semantic query parameters."""
    try:
        u = urlsplit(url)
        if u.scheme.lower() not in ('http', 'https') or not u.hostname:
            return ''
        host = u.hostname.lower().rstrip('.')
        if u.port and u.port not in (80, 443):
            netloc = f'{host}:{u.port}'
        else:
            netloc = host
        query = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
                 if not k.lower().startswith('utm_') and k.lower() not in TRACKING]
        query.sort()
        path = re.sub(r'/+', '/', u.path or '/')
        if path != '/':
            path = path.rstrip('/')
        return urlunsplit((u.scheme.lower(), netloc, path, urlencode(query), ''))
    except (ValueError, TypeError):
        return ''


def _words(text: str) -> set[str]:
    normalized = unicodedata.normalize('NFKC', text or '').lower()
    words = set(re.findall(r'[a-z][a-z0-9.\-]{2,}|\d+(?:\.\d+)*|[\u3040-\u30ff\u3400-\u9fff]{3,}', normalized))
    return {w for w in words if w not in STOPWORDS}


def _entities(text: str) -> set[str]:
    return {name for name, pattern in ENTITY_ALIASES.items() if re.search(pattern, text, flags=re.I)}


def _actions(text: str) -> set[str]:
    return {name for name, pattern in ACTION_ALIASES.items() if re.search(pattern, text, flags=re.I)}


def _date_near(a: dict, b: dict) -> bool:
    try:
        da = dt.date.fromisoformat(a.get('date', '')[:10])
        db = dt.date.fromisoformat(b.get('date', '')[:10])
        return abs((da - db).days) <= 4
    except ValueError:
        return False


def same_story(a: dict, b: dict) -> bool:
    """Conservative matching: product similarity alone MUST NOT collapse events."""
    ua, ub = normalize_url(a.get('url', '')), normalize_url(b.get('url', ''))
    if ua and ua == ub:
        return True
    # Distinct semantic article IDs in the same endpoint are not URL duplicates.
    pa, pb = urlsplit(ua), urlsplit(ub)
    if (pa.netloc == pb.netloc and pa.path == pb.path and
            pa.query and pb.query and pa.query != pb.query):
        return False
    ta = unicodedata.normalize('NFKC', a.get('title', '')).lower().strip()
    tb = unicodedata.normalize('NFKC', b.get('title', '')).lower().strip()
    if ta and ta == tb and _date_near(a, b):
        return True
    if not _date_near(a, b):
        return False
    ea, eb = _entities(ta), _entities(tb)
    if not ea or not eb or not ea.intersection(eb):
        return False
    aa, ab = _actions(ta), _actions(tb)
    # Different story types (price vs security, release vs research) must survive.
    if aa and ab and not (aa & ab):
        return False
    wa, wb = _words(ta), _words(tb)
    if not wa or not wb:
        return False
    overlap = len(wa & wb) / len(wa | wb)
    # Cross-site titles often use different verbs. Require substantial common
    # facts; a name and the word 'release' by themselves are insufficient.
    shared_specific = (wa & wb) - ea - {'release', 'update', 'version'}
    return overlap >= 0.52 and len(shared_specific) >= 2


def _official(item: dict) -> bool:
    host = (urlsplit(item.get('url', '')).hostname or '').lower()
    return any(host == h or host.endswith('.' + h) for h in (
        'openai.com', 'google.com', 'deepmind.google', 'huggingface.co',
        'github.com', 'github.blog', 'anthropic.com', 'microsoft.com'))


def group_stories(items: list[dict]) -> list[dict]:
    """Keep one lead per event and retain supplemental URLs."""
    groups: list[list[dict]] = []
    for item in items:
        item = dict(item)
        item['url'] = normalize_url(item.get('url', ''))
        if not item['url']:
            continue
        for group in groups:
            if any(same_story(item, other) for other in group):
                if item['url'] not in {x['url'] for x in group}:
                    group.append(item)
                break
        else:
            groups.append([item])
    result = []
    for group in groups:
        # Body status evaluated later too, after fetching. Original ordering
        # breaks ties, preserving the user's editorial selection.
        representative = max(group, key=lambda x: (
            x.get('evidence_status') == 'body', _official(x),
            bool(x.get('date'))))
        record = dict(representative)
        supplements = list(record.get('supporting_sources') or [])
        supplements.extend(
            {'source': x.get('source', ''), 'url': x['url'], 'title': x.get('title', ''),
             'date': x.get('date', ''), 'evidence_status': x.get('evidence_status', 'summary_only')}
            for x in group if x is not representative)
        record['supporting_sources'] = list({x['url']: x for x in supplements}.values())
        result.append(record)
    return result


class _Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.scopes = 0
        self.in_para = 0
        self.current: list[str] = []
        self.scoped: list[str] = []
        self.fallback: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'nav', 'footer', 'header', 'noscript'):
            self.skip += 1
        if tag in ('article', 'main'):
            self.scopes += 1
        if tag == 'p':
            self.in_para += 1
            self.current = []

    def handle_data(self, data):
        if self.in_para and not self.skip:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == 'p' and self.in_para:
            line = re.sub(r'\s+', ' ', html.unescape(''.join(self.current))).strip()
            if len(line) >= 40:
                self.fallback.append(line)
                if self.scopes:
                    self.scoped.append(line)
            self.in_para = max(0, self.in_para - 1)
            self.current = []
        if tag in ('article', 'main'):
            self.scopes = max(0, self.scopes - 1)
        if tag in ('script', 'style', 'nav', 'footer', 'header', 'noscript'):
            self.skip = max(0, self.skip - 1)


def _safe_public_https(url: str) -> bool:
    parsed = urlsplit(url)
    host = parsed.hostname or ''
    if parsed.scheme != 'https' or not host or parsed.username or parsed.password:
        return False
    if host in ('localhost', 'metadata.google.internal', 'metadata', 'localhost.localdomain'):
        return False
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_global
    except ValueError:
        return '.' in host and not host.endswith(('.local', '.internal', '.localhost'))


def _bounded_get(session, url, limit=MAX_BYTES, allow_url=None):
    """No auto-redirects, stream cap, and HTTP timeout. Redirects checked again."""
    for _ in range(3):
        if not _safe_public_https(url):
            raise ValueError('URL is not a public HTTPS article')
        if allow_url is not None and not allow_url(url):
            raise ValueError('robots disallowed article URL')
        response = session.get(url, timeout=(4, 9), stream=True, allow_redirects=False,
                               headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,text/plain'})
        try:
            if response.status_code in (301, 302, 303, 307, 308):
                target = urljoin(url, response.headers.get('Location', ''))
                url = target
                continue
            response.raise_for_status()
            if 'text/html' not in response.headers.get('Content-Type', 'text/html'):
                raise ValueError('Not an HTML page')
            payload = bytearray()
            for chunk in response.iter_content(chunk_size=8192):
                payload.extend(chunk)
                if len(payload) > limit:
                    raise ValueError('Article exceeds download size limit')
            return bytes(payload).decode(response.encoding or 'utf-8', errors='replace')
        finally:
            response.close()
    raise ValueError('Too many redirects')


class ArticleFetcher:
    def __init__(self, session=None):
        self.session = session or requests.Session()
        self.robots_cache = {}

    def allowed(self, url: str) -> bool:
        if not _safe_public_https(url):
            return False
        host = urlsplit(url).netloc
        if host not in self.robots_cache:
            robots_url = f'https://{host}/robots.txt'
            try:
                r = self.session.get(robots_url, timeout=(3, 5),
                                     allow_redirects=False,
                                     headers={'User-Agent': USER_AGENT})
                if r.status_code == 404:
                    self.robots_cache[host] = True
                elif r.status_code != 200:
                    self.robots_cache[host] = False
                else:
                    p = RobotFileParser()
                    p.parse(r.text.splitlines())
                    self.robots_cache[host] = p
            except requests.RequestException:
                self.robots_cache[host] = False
        rule = self.robots_cache[host]
        return rule if isinstance(rule, bool) else rule.can_fetch(USER_AGENT, url)

    def enrich(self, item: dict) -> dict:
        result = {**item, 'evidence_status': 'summary_only', 'facts': []}
        url = result.get('url', '')
        if not self.allowed(url):
            result['fetch_reason'] = 'robots_disallowed_or_unavailable'
            return result
        try:
            markup = _bounded_get(self.session, url, allow_url=self.allowed)
            parser = _Paragraphs()
            parser.feed(markup)
            # Only a recognizable main/article scope is strong enough evidence.
            # Site-wide paragraphs could be advertising, cookie notices or nav.
            lines = parser.scoped
            total = sum(len(p) for p in lines)
            if total < MIN_BODY_CHARS:
                result['fetch_reason'] = 'insufficient_article_text'
                return result
            result['evidence_status'] = 'body'
            result['facts'] = [line[:220] for line in lines[:MAX_EXCERPTS]]
            result['fetch_reason'] = 'verified_article_paragraphs'
            return result
        except (requests.RequestException, ValueError, UnicodeError) as error:
            result['fetch_reason'] = type(error).__name__
            return result


def collect_evidence(stories: list[dict], fetcher=None, max_articles=MAX_ARTICLES) -> list[dict]:
    """Attempt only a bounded shortlist; unavailable sources remain headline-only."""
    fetcher = fetcher or ArticleFetcher()
    collected = []
    for pos, item in enumerate(stories):
        collected.append(fetcher.enrich(item) if pos < max_articles else {
            **item, 'evidence_status': 'summary_only', 'facts': [],
            'fetch_reason': 'article_limit'})
    return collected


def public_sources(stories: list[dict]) -> list[dict]:
    """Strip excerpts and raw article bodies from GitHub Pages JSON."""
    fields = ('source', 'title', 'url', 'date', 'evidence_status', 'fetch_reason')
    return [{**{k: s[k] for k in fields if k in s},
             'supporting_sources': s.get('supporting_sources', [])}
            for s in stories]