"""Verify that a published episode has playable audio and matching metadata."""
import argparse
import datetime as dt
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EP = ROOT / 'episodes'
JST = dt.timezone(dt.timedelta(hours=9))


def check_episode(day, base=EP, probe=False):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day):
        raise ValueError(f'Invalid episode date: {day}')
    meta_path, audio_path = base / f'{day}.json', base / f'{day}.mp3'
    if not meta_path.is_file() or not audio_path.is_file():
        raise RuntimeError(f'Missing JSON or MP3 for {day}')
    if audio_path.stat().st_size < 4096:
        raise RuntimeError(f'MP3 is suspiciously small for {day}')
    data = json.loads(meta_path.read_text(encoding='utf-8'))
    if data.get('date') != day or data.get('audio') != f'episodes/{day}.mp3':
        raise ValueError(f'Invalid date or audio path in {day}.json')
    if not isinstance(data.get('title'), str) or not data['title'].strip():
        raise ValueError(f'Missing episode title for {day}')
    duration = data.get('duration_seconds')
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise ValueError(f'Invalid duration for {day}')
    if probe:
        out = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(audio_path)],
            check=True, capture_output=True, text=True)
        actual = float(out.stdout.strip())
        if abs(actual - duration) > 3:
            raise RuntimeError(f'MP3/JSON duration mismatch for {day}: {actual} vs {duration}')
    print(f'Verified episode {day}: {duration}s, {audio_path.stat().st_size} bytes', flush=True)
    return data


def check_archive(base=EP):
    path = base / 'index.json'
    items = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(items, list) or not 1 <= len(items) <= 7:
        raise ValueError('Archive must contain 1-7 episodes')
    dates = [e['date'] for e in items]
    if dates != sorted(set(dates), reverse=True):
        raise ValueError('Archive dates must be unique and newest first')
    for item in items:
        meta = check_episode(item['date'], base=base)
        for key in ('title', 'audio', 'duration_seconds'):
            if item.get(key) != meta[key]:
                raise ValueError(f'Archive metadata differs for {item["date"]}: {key}')
    print(f'Verified archive: {len(items)} playable episode references', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--episode', nargs='?', const=dt.datetime.now(JST).date().isoformat())
    modes.add_argument('--archive', action='store_true')
    args = parser.parse_args()
    if args.archive:
        check_archive()
    else:
        check_episode(args.episode, probe=True)
