"""Verify the deployed archive against the exact validated Pages artifact.

This is a read-only delivery check. A failed check never regenerates audio or
changes the deployed archive; retry Pages publication after diagnosing it.
"""
from __future__ import annotations

import argparse
import hashlib
from http.client import HTTPException
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit, urljoin
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from scripts import verify, work_script
except ModuleNotFoundError:
    import verify
    import work_script

ROOT = Path(__file__).resolve().parents[1]
CHUNK_SIZE = 64 * 1024


def checked_base_url(value):
    work_script.source_url(value)
    parsed = urlsplit(value)
    if parsed.query or parsed.fragment:
        raise ValueError('Pages URL must not contain a query or fragment')
    return value.rstrip('/') + '/'


class SameOriginRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urlsplit(req.full_url), urlsplit(newurl)
        if (new.scheme, new.hostname, new.port) != (old.scheme, old.hostname, old.port):
            raise ValueError('Live archive redirect changed origin')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def file_digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b''):
            result.update(chunk)
    return result.hexdigest()


def snapshot(episodes):
    """Capture only validated, date-scoped artifact files, never arbitrary paths."""
    episodes = Path(episodes)
    verify.check_archive(base=episodes)
    items = json.loads((episodes / 'index.json').read_text(encoding='utf-8'))
    paths = ['index.json']
    for item in items:
        day = work_script.date(item['date'])
        paths.extend([f'{day}.json', f'{day}.mp3'])
    return items, {
        name: (episodes / name, (episodes / name).stat().st_size, file_digest(episodes / name))
        for name in paths
    }


def check_file(base_url, name, size, digest, opener):
    if name != 'index.json' and not re.fullmatch(r'\d{4}-\d{2}-\d{2}\.(?:json|mp3)', name):
        raise ValueError('Invalid live archive path')
    url = urljoin(base_url, 'episodes/' + name)
    request = Request(url, headers={'Cache-Control': 'no-cache', 'User-Agent': 'MASURADIO-delivery-check'})
    actual, count = hashlib.sha256(), 0
    with opener.open(request, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(f'Live archive HTTP failure: {name}')
        while True:
            chunk = response.read(min(CHUNK_SIZE, size - count + 1))
            if not chunk:
                break
            count += len(chunk)
            if count > size:
                raise RuntimeError(f'Live archive size differs: {name}')
            actual.update(chunk)
    if count != size or actual.hexdigest() != digest:
        raise RuntimeError(f'Live archive differs from validated artifact: {name}')


def check_live(base_url, episodes=ROOT / 'episodes', *, attempts=3, retry_delay=5, opener=None):
    base_url = checked_base_url(base_url)
    if type(attempts) is not int or not 1 <= attempts <= 5:
        raise ValueError('Expected 1-5 live verification attempts')
    if not isinstance(retry_delay, (int, float)) or not 0 <= retry_delay <= 30:
        raise ValueError('Invalid live verification retry delay')
    items, files = snapshot(episodes)
    opener = opener or build_opener(SameOriginRedirect())
    for attempt in range(attempts):
        try:
            for name, (_, size, digest) in files.items():
                check_file(base_url, name, size, digest, opener)
        except (OSError, ValueError, RuntimeError, HTTPException) as error:
            if attempt + 1 == attempts:
                raise RuntimeError('Live archive verification failed; do not regenerate audio. '
                                   'Inspect Pages delivery and retry publication if needed.') from error
            print(f'Live archive not verified yet; retry {attempt + 1}/{attempts - 1}', flush=True)
            time.sleep(retry_delay)
        else:
            result = {'latest_date': items[0]['date'], 'episodes': len(items),
                      'verified_files': len(files), 'base_url': base_url}
            print('Live archive verified:', json.dumps(result, ensure_ascii=False), flush=True)
            return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--attempts', type=int, default=3)
    args = parser.parse_args()
    check_live(args.base_url, attempts=args.attempts)
