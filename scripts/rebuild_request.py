"""Date-scoped, once-per-success episode rebuild requests reviewed through a PR."""
import datetime as dt
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
JST = dt.timezone(dt.timedelta(hours=9))


def request_id(day, request_file=None):
    path = request_file or ROOT / '.github/rebuild-request.json'
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(value, dict) or set(value) != {'date', 'request_id'}
            or not isinstance(value['date'], str)
            or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value['date'])
            or not isinstance(value['request_id'], str)
            or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', value['request_id'])):
        raise ValueError('Invalid rebuild request format')
    dt.date.fromisoformat(value['date'])
    return value['request_id'] if value['date'] == day else None


def pending(day, request_file=None, episodes=None):
    wanted = request_id(day, request_file)
    if wanted is None:
        return False
    path = (episodes or ROOT / 'episodes') / f'{day}.json'
    try:
        episode = json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return True
    return (not isinstance(episode, dict) or episode.get('date') != day
            or episode.get('rebuild_request_id') != wanted)


if __name__ == '__main__':
    day = dt.datetime.now(JST).date().isoformat()
    print('true' if pending(day) else 'false')
