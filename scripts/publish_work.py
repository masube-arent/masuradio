"""Render a reviewed Work script without RSS writing or any Gemini calls."""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

try:
    from scripts import generate, rebuild_request, stage_resume, story_quality, verify, work_script
except ModuleNotFoundError:
    import generate, rebuild_request, stage_resume, story_quality, verify, work_script

ROOT = Path(__file__).resolve().parents[1]
JST = dt.timezone(dt.timedelta(hours=9))


def publish(root, day, replace_existing=False):
    root = Path(root)
    prepared = work_script.load_submission(root, day)
    data, review = prepared['data'], prepared['review']
    episodes = root / 'episodes'
    metadata_path = episodes / f'{day}.json'
    if metadata_path.exists():
        # An incomplete pair can be recovered; a valid different broadcast is protected.
        try:
            old = verify.check_episode(day, base=episodes, probe=True)
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError):
            old = None
        if old and old.get('script_hash') == prepared['script_hash']:
            request = rebuild_request.request_id(day, root / '.github/rebuild-request.json')
            if request and old.get('rebuild_request_id') != request:
                # Consume an authorized request without synthesizing identical speech.
                # Validate the updated pair before atomically replacing only its JSON.
                updated = dict(old, rebuild_request_id=request)
                with tempfile.TemporaryDirectory(prefix='.radio-review-', dir=episodes) as directory:
                    staged = Path(directory)
                    shutil.copyfile(episodes / f'{day}.mp3', staged / f'{day}.mp3')
                    stage_resume.atomic_json(staged / f'{day}.json', updated)
                    verify.check_episode(day, base=staged, probe=True)
                    os.replace(staged / f'{day}.json', metadata_path)
                old = updated
            print('Completed Work script already published; no TTS or Gemini call')
            return old
        if old and not replace_existing:
            raise ValueError('A different complete episode exists; explicit replacement required')
    stage = stage_resume.StageCache(root / '.radio-cache', day)
    with tempfile.TemporaryDirectory(prefix='masuradio-work-') as directory:
        audio, duration, measured = asyncio.run(generate.render(prepared['segments'], Path(directory), stage))
        public_sources = story_quality.public_sources(prepared['sources'])
        metadata = {
            'date': day, 'title': data['episode_title'], 'episode_title': data['episode_title'],
            'audio': f'episodes/{day}.mp3', 'duration_seconds': duration,
            'sources': public_sources, 'featured_sources': public_sources,
            'script': prepared['segments'], 'host': 'NANA',
            'chapters': stage_resume.chapters_for_parts(prepared['starts'], measured, duration, prepared['labels']),
            'topics': prepared['labels'],
            'production_method': 'work-researched-script', 'script_id': data['script_id'],
            'script_hash': prepared['script_hash'],
            'editorial_review': {'method': review['reviewer'], 'reviewed_at': review['reviewed_at'],
                                 'script_sha256': review['script_sha256']},
            'gemini_usage': {'api_calls': 0, 'prompt_tokens': 0, 'output_tokens': 0,
                             'thinking_tokens': 0, 'total_tokens': 0, 'estimated_usd': 0},
        }
        request = rebuild_request.request_id(day, root / '.github/rebuild-request.json')
        if request:
            metadata['rebuild_request_id'] = request
        stage_resume.verified_publish(audio, metadata, episodes, day, verify.check_episode)
    for old in sorted(episodes.glob('????-??-??.mp3'))[:-7]:
        old.unlink(missing_ok=True)
        old.with_suffix('.json').unlink(missing_ok=True)
    print('Generated reviewed Work episode:', day, duration, 'seconds; Gemini calls: 0')
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', default=dt.datetime.now(JST).date().isoformat())
    parser.add_argument('--replace-existing', action='store_true')
    args = parser.parse_args()
    work_script.date(args.date)
    request_pending = rebuild_request.pending(args.date)
    publish(ROOT, args.date, replace_existing=args.replace_existing or request_pending)
