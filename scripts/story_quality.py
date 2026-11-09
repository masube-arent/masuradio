"""Bounded, respectful evidence gathering and conservative multi-source deduplication.

Article snippets are strictly transient generation input: never serialize excerpts to
public episode metadata. No credentials, login, paywall bypass or paid AI calls.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
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
# Modern official pages include large application shells. Still cap decoded bytes.
MAX_BYTES = 2_000_000
MAX_ROBOTS_BYTES = 64_000
MIN_BODY_CHARS = 200
MAX_EXCERPTS = 8
MAX_EXCERPT_CHARS = 6000
# Preserve complete paragraphs, including the qualifications after a number.
EVIDENCE_SIGNALS = re.compile(
    r"\d|develop|creat|built|author|licen[cs]e|commercial|language|support|"
    r"limitation|compar|baseline|median|review|latency|gradium|開発|言語|ライセンス|比較", re.I)
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
    """Extract complete body blocks, with headings and list introductions intact.

    Release pages have a large site UI inside <main>. Only their explicit rendered
    Markdown body is evidence. Lists elsewhere require an article scope, rather
    than treating navigation/menu links as release notes.
    """
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
            'link', 'meta', 'param', 'source', 'track', 'wbr'}
    SKIP = {'script', 'style', 'nav', 'footer', 'noscript', 'aside',
            'form', 'button', 'menu'}

    def __init__(self, article_url="", resolved_url=""):
        super().__init__(convert_charrefs=True)
        self.article_urls = {normalize_url(u) for u in (article_url, resolved_url) if u}
        parsed = urlsplit(resolved_url or article_url)
        self.release_page = (parsed.hostname == 'github.com' and
                             bool(re.fullmatch(r'/[^/]+/[^/]+/releases/tag/[^/]+/?', parsed.path)))
        self.stack = []
        self.skip = 0
        self.scopes = 0
        self.articles = 0
        self.releases = 0
        self.has_article = False
        self.block = None
        self.heading = None
        self.headings = []
        self.list_introductions = []
        self.previous_paragraph = ''
        self.scoped: list[str] = []
        self.article_scoped: list[str] = []
        self.body_lengths: dict[str, int] = {}
        self.publication_dates: list[str] = []
        self.in_jsonld = False
        self.jsonld: list[str] = []

    def _is_body(self, tag):
        if self.release_page:
            return bool(self.releases)
        return bool(self.articles if tag in ('ul', 'ol') else self.scopes)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'meta' and attributes.get('property', '').lower() == 'article:published_time':
            self.publication_dates.append(attributes.get('content', ''))
        if tag == 'script' and attributes.get('type', '').lower() == 'application/ld+json':
            self.in_jsonld = True
            self.jsonld = []
        skipped = (tag in self.SKIP or (tag == 'header' and not self.articles) or
                   'hidden' in attributes or attributes.get('aria-hidden') == 'true' or
                   attributes.get('role') in ('navigation', 'complementary'))
        scoped = tag in ('article', 'main') and not (self.skip or skipped)
        article = tag == 'article' and scoped
        self.has_article = self.has_article or article
        release = (self.release_page and tag == 'div' and
                   'markdown-body' in attributes.get('class', '').split() and
                   not (self.skip or skipped))
        if tag not in self.VOID:
            self.stack.append((tag, skipped, scoped, article, release))
            self.skip += skipped
            self.scopes += scoped
            self.articles += article
            self.releases += release
        if self.skip or skipped:
            return
        if self.block:
            if tag in ('p', 'li', 'ul', 'ol', 'br'):
                self.block['parts'].append(' ')
            return
        if self.release_page and tag in ('ul', 'ol') and self._is_body(tag):
            self.list_introductions.append((len(self.stack), self.previous_paragraph))
            self.previous_paragraph = ''
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6') and self._is_body(tag):
            owner = next((i + 1 for i in range(len(self.stack) - 1, -1, -1)
                          if self.stack[i][0] in ('article', 'section', 'main') or self.stack[i][4]), 0)
            self.heading = {'depth': len(self.stack), 'level': int(tag[1]),
                            'owner': owner, 'parts': []}
        elif tag in (('p', 'li') if self.release_page else ('p', 'ul', 'ol')) and self._is_body(tag):
            context = [text for _, text, _ in self.headings]
            if tag in ('ul', 'ol') and self.previous_paragraph:
                context.append(self.previous_paragraph)
            if tag == 'li' and self.list_introductions and self.list_introductions[-1][1]:
                context.append(self.list_introductions[-1][1])
            self.block = {'depth': len(self.stack), 'tag': tag, 'parts': [],
                          'context': context, 'article': bool(self.articles)}

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_data(self, data):
        if self.in_jsonld:
            self.jsonld.append(data)
        if not self.skip:
            if self.block:
                self.block['parts'].append(data)
            elif self.heading:
                self.heading['parts'].append(data)

    def _jsonld_date(self):
        try:
            payload = json.loads(''.join(self.jsonld))
            def visit(value):
                if isinstance(value, list):
                    for child in value:
                        visit(child)
                elif isinstance(value, dict):
                    # Ignore organization/product dates and dateModified.
                    types = value.get('@type', [])
                    types = [types] if isinstance(types, str) else types
                    refs = [value.get('url'), value.get('@id'), value.get('mainEntityOfPage')]
                    refs = [r.get('@id') if isinstance(r, dict) else r for r in refs]
                    matches_article = any(isinstance(r, str) and
                                          normalize_url(r) in self.article_urls for r in refs)
                    if matches_article and isinstance(types, list) and any(
                            t in ('Article', 'NewsArticle', 'BlogPosting', 'TechArticle')
                            for t in types if isinstance(t, str)):
                        self.publication_dates.append(value.get('datePublished', ''))
                    if '@graph' in value:
                        visit(value['@graph'])
            visit(payload)
        except (ValueError, TypeError, RecursionError):
            pass

    def handle_endtag(self, tag):
        if tag == 'script' and self.in_jsonld:
            self.in_jsonld = False
            self._jsonld_date()
        index = next((i for i in range(len(self.stack) - 1, -1, -1)
                      if self.stack[i][0] == tag), None)
        if index is None:
            return
        depth = index + 1
        if self.block and depth <= self.block['depth']:
            # A parent closing around an unclosed block is not a complete claim.
            if depth == self.block['depth'] and not self.skip:
                line = re.sub(r'\s+', ' ', ''.join(self.block['parts'])).strip()
                # Oversized blocks or heading paths are skipped, never sliced.
                size = len(line) + sum(len(x) + 1 for x in self.block['context'])
                if len(line) >= 20 and size <= MAX_EXCERPT_CHARS:
                    excerpt = '\n'.join(self.block['context'] + [line])
                    self.scoped.append(excerpt)
                    if self.block['article']:
                        self.article_scoped.append(excerpt)
                    self.body_lengths[excerpt] = len(line)
                self.previous_paragraph = line if self.block['tag'] == 'p' else ''
            self.block = None
        elif self.block and tag in ('p', 'li', 'ul', 'ol'):
            self.block['parts'].append(' ')
        if self.heading and depth <= self.heading['depth']:
            if depth == self.heading['depth'] and not self.skip:
                line = re.sub(r'\s+', ' ', ''.join(self.heading['parts'])).strip()
                level = self.heading['level']
                self.headings = [(n, text, owner) for n, text, owner in self.headings if n < level]
                if line:
                    self.headings.append((level, line, self.heading['owner']))
                self.previous_paragraph = ''
            self.heading = None
        self.headings = [(n, text, owner) for n, text, owner in self.headings if owner < depth]
        self.list_introductions = [(n, text) for n, text in self.list_introductions if n < depth]
        for element, skipped, scoped, article, release in self.stack[index:]:
            if article or release or element == 'section':
                self.previous_paragraph = ''
            self.skip -= skipped
            self.scopes -= scoped
            self.articles -= article
            self.releases -= release
        del self.stack[index:]
        if not self.scopes and not self.releases:
            self.headings = []
            self.previous_paragraph = ''



def _publication_date(values: list[str]) -> str:
    """Keep the publisher's calendar date; conflicting metadata is not evidence."""
    dates = set()
    for value in values:
        if not isinstance(value, str) or not re.match(r'^\d{4}-\d{2}-\d{2}(?:T|$| )', value):
            continue
        try:
            dates.add(dt.date.fromisoformat(value[:10]).isoformat())
        except ValueError:
            continue
    return next(iter(dates)) if len(dates) == 1 else ''


def select_excerpts(lines: list[str], url: str) -> list[dict]:
    """Bounded, whole paragraphs: skip oversized blocks rather than invent an ending.

    Cover the introduction and informative paragraphs throughout the article.
    Selection is not fact verification: the model must still preserve metric,
    comparison, attribution and other qualifications in each selected excerpt.
    """
    indexed = list(enumerate(dict.fromkeys(lines)))
    ranked = sorted(indexed, key=lambda row: (
        row[0] != 0, -len(EVIDENCE_SIGNALS.findall(row[1])), row[0]))
    chosen, size = [], 0
    for index, text in ranked:
        if len(chosen) >= MAX_EXCERPTS:
            break
        if size + len(text) > MAX_EXCERPT_CHARS:
            continue
        digest = hashlib.sha256((normalize_url(url) + '\n' + text).encode()).hexdigest()[:16]
        chosen.append((index, {'id': 'e_' + digest, 'text': text}))
        size += len(text)
    return [excerpt for _, excerpt in sorted(chosen)]


def _safe_public_https(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower().rstrip('.')
        if parsed.port not in (None, 443):
            return False
    except (ValueError, TypeError):
        return False
    if parsed.scheme != 'https' or not host or parsed.username or parsed.password:
        return False
    if host in ('localhost', 'metadata.google.internal', 'metadata', 'localhost.localdomain'):
        return False
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_global
    except ValueError:
        # Alternative numeric IPv4 spellings can resolve to loopback even though
        # ipaddress rejects them. Do not pass them to the HTTP client's resolver.
        if re.fullmatch(r'(?:0x[0-9a-f]+|\d+)(?:\.(?:0x[0-9a-f]+|\d+))*', host, re.I):
            return False
        return '.' in host and not host.endswith(('.local', '.internal', '.localhost'))


class EvidenceFetchError(ValueError):
    """Fixed diagnostic codes only; never publish page content or error URLs."""


def _bounded_get(session, url, limit=MAX_BYTES, allow_url=None, return_url=False):
    """No auto-redirects, stream cap, and HTTP timeout. Redirects checked again."""
    for _ in range(3):
        if not _safe_public_https(url):
            raise EvidenceFetchError('unsafe_article_url')
        if allow_url is not None and not allow_url(url):
            raise EvidenceFetchError('robots_disallowed_or_unavailable')
        response = session.get(url, timeout=(4, 9), stream=True, allow_redirects=False,
                               headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,text/plain'})
        try:
            if response.status_code in (301, 302, 303, 307, 308):
                if not response.headers.get('Location'):
                    raise EvidenceFetchError('redirect_missing_location')
                target = urljoin(url, response.headers['Location'])
                url = target
                continue
            response.raise_for_status()
            if 'text/html' not in response.headers.get('Content-Type', 'text/html'):
                raise EvidenceFetchError('unsupported_content_type')
            payload = bytearray()
            for chunk in response.iter_content(chunk_size=8192):
                payload.extend(chunk)
                if len(payload) > limit:
                    raise EvidenceFetchError('article_size_limit')
            markup = bytes(payload).decode(response.encoding or 'utf-8', errors='replace')
            return (markup, url) if return_url else markup
        finally:
            response.close()
    raise EvidenceFetchError('redirect_limit')


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
            r = None
            try:
                r = self.session.get(robots_url, timeout=(3, 5),
                                     allow_redirects=False, stream=True,
                                     headers={'User-Agent': USER_AGENT})
                if r.status_code == 404:
                    self.robots_cache[host] = True
                elif r.status_code != 200:
                    self.robots_cache[host] = False
                else:
                    payload = bytearray()
                    for chunk in r.iter_content(chunk_size=8192):
                        payload.extend(chunk)
                        if len(payload) > MAX_ROBOTS_BYTES:
                            raise EvidenceFetchError('robots_size_limit')
                    p = RobotFileParser()
                    p.parse(bytes(payload).decode(r.encoding or 'utf-8', errors='replace').splitlines())
                    self.robots_cache[host] = p
            except (requests.RequestException, ValueError):
                self.robots_cache[host] = False
            finally:
                if r is not None:
                    r.close()
        rule = self.robots_cache[host]
        return rule if isinstance(rule, bool) else rule.can_fetch(USER_AGENT, url)

    def enrich(self, item: dict) -> dict:
        result = {**item, 'evidence_status': 'summary_only', 'facts': [],
                  'evidence_excerpts': [], 'article_published_date': ''}
        url = result.get('url', '')
        if not self.allowed(url):
            result['fetch_reason'] = 'robots_disallowed_or_unavailable'
            return result
        try:
            markup, resolved_url = _bounded_get(self.session, url, allow_url=self.allowed,
                                                return_url=True)
            parser = _Paragraphs(url, resolved_url)
            parser.feed(markup)
            parser.close()
            # Only a recognizable main/article scope is strong enough evidence.
            # Site-wide paragraphs could be advertising, cookie notices or nav.
            lines = (parser.article_scoped if parser.has_article and not parser.release_page
                     else parser.scoped)
            # Repeated headings/list introductions cannot inflate body coverage.
            total = sum(parser.body_lengths[line] for line in set(lines))
            if total < MIN_BODY_CHARS:
                result['fetch_reason'] = 'insufficient_article_text'
                return result
            excerpts = select_excerpts(lines, url)
            if sum(parser.body_lengths[x['text']] for x in excerpts) < MIN_BODY_CHARS:
                result['fetch_reason'] = 'insufficient_bounded_article_text'
                return result
            result['evidence_status'] = 'body'
            result['evidence_excerpts'] = excerpts
            result['facts'] = [x['text'] for x in excerpts]
            result['article_published_date'] = _publication_date(parser.publication_dates)
            result['fetch_reason'] = 'verified_article_paragraphs'
            return result
        except EvidenceFetchError as error:
            result['fetch_reason'] = str(error)
            return result
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            result['fetch_reason'] = f'http_{status}' if isinstance(status, int) else 'http_error'
            return result
        except requests.Timeout:
            result['fetch_reason'] = 'request_timeout'
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
            'evidence_excerpts': [], 'article_published_date': '',
            'fetch_reason': 'article_limit'})
    return collected


def public_sources(stories: list[dict]) -> list[dict]:
    """Strip excerpts and raw article bodies from GitHub Pages JSON."""
    fields = ('source', 'title', 'url', 'date', 'article_published_date',
              'evidence_status', 'fetch_reason')
    return [{**{k: s[k] for k in fields if k in s},
             'supporting_sources': [{k: x[k] for k in fields if k in x}
                                    for x in s.get('supporting_sources', [])]}
            for s in stories]
