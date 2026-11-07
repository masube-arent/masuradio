"""Crash-safe local stages, reusable across GitHub Actions cache restores.

Successful JSON stages are keyed by actual inputs and version; audio by the
exact normalized spoken text, voice and rate. Never trust partial files.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


STAGE_VERSION = 'masuradio-stages-v2'


def digest(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), default=str).encode('utf-8')).hexdigest()


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.partial-', suffix='.json', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(value, output, ensure_ascii=False, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def probe_audio(path):
    if not path.is_file() or path.stat().st_size < 256:
        return None
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
            check=True, capture_output=True, text=True, timeout=20)
        duration = float(result.stdout.strip())
        return duration if 0.1 < duration < 3600 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


class StageCache:
    def __init__(self, base, day):
        if len(day) != 10 or day[4] != '-' or day[7] != '-':
            raise ValueError('Date must be ISO YYYY-MM-DD')
        self.root = Path(base) / day
        self.root.mkdir(parents=True, exist_ok=True)

    def json(self, name, inputs, create, validate=lambda v: True):
        """Return (value, reused). Corrupt/stale/partial entries are ignored."""
        key = digest({'version': STAGE_VERSION, 'name': name, 'inputs': inputs})
        path = self.root / 'json' / f'{name}-{key[:24]}.json'
        if path.is_file():
            try:
                record = json.loads(path.read_text(encoding='utf-8'))
                value = record['value']
                if (record.get('complete') is True and record.get('key') == key
                        and record.get('checksum') == digest(value)
                        and validate(value)):
                    print(f'[reuse] {name} {key[:12]}', flush=True)
                    return value, True
            except (OSError, ValueError, KeyError, TypeError):
                pass
        print(f'[new] {name} {key[:12]}', flush=True)
        value = create()
        if not validate(value):
            raise ValueError(f'{name}: stage validation failed')
        record = {'complete': True, 'key': key, 'checksum': digest(value), 'value': value}
        atomic_json(path, record)
        return value, False

    def file(self, name, inputs, create):
        """Cache a merged MP3 under a content key, committing only after validation.

        create receives a temporary Path; failures leave the previous cache intact.
        """
        key = digest({'version': STAGE_VERSION, 'name': name, 'inputs': inputs})
        path = self.root / 'merged' / f'{name}-{key}.mp3'
        duration = probe_audio(path)
        if duration is not None:
            print(f'[reuse] {name} {key[:12]} {duration:.2f}s', flush=True)
            return path, duration, True
        print(f'[new] {name} {key[:12]}', flush=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name_tmp = tempfile.mkstemp(prefix='.partial-', suffix='.mp3', dir=path.parent)
        os.close(fd)
        tmp = Path(name_tmp)
        try:
            create(tmp)
            duration = probe_audio(tmp)
            if duration is None:
                raise RuntimeError(f'{name}: incomplete MP3')
            os.replace(tmp, path)
            return path, duration, False
        finally:
            tmp.unlink(missing_ok=True)

    async def audio(self, text, voice, rate, produce, *, engine='edge-tts-v7'):
        """Synthesize only on a cache miss; write to .partial before commit."""
        key = digest({'text': text, 'voice': voice, 'rate': rate, 'engine': engine})
        path = self.root / 'audio' / f'{key}.mp3'
        duration = probe_audio(path)
        if duration is not None:
            print(f'[reuse] tts {key[:12]} {duration:.2f}s', flush=True)
            return path, duration, True
        print(f'[new] tts {key[:12]}', flush=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.partial-', suffix='.mp3', dir=path.parent)
        os.close(fd)
        tmp = Path(name)
        try:
            await produce(tmp)
            duration = probe_audio(tmp)
            if duration is None:
                raise RuntimeError('Incomplete or invalid synthesized audio')
            os.replace(tmp, path)
            return path, duration, False
        finally:
            tmp.unlink(missing_ok=True)


def chapters_for_parts(part_starts, segment_durations, finished_duration, labels=None):
    """Create cue points measured from actual segment audio, not text lengths.

    MP3 concatenation and tempo conversion can change the exact overall timing.
    Scale the measured segment boundaries by the ratio to the probed final file.
    """
    labels = labels or ('ニュース', '深掘り', '別角度の話題', '実践・まとめ')
    if not segment_durations or finished_duration <= 0:
        return []
    if any(v <= 0 for v in segment_durations):
        raise ValueError('Invalid audio segment duration')
    original = sum(segment_durations)
    total = len(segment_durations)
    if not all(isinstance(i, int) and 0 <= i < total for i in part_starts):
        raise ValueError('Chapter indices outside audio')
    result = []
    for i, start in enumerate(part_starts):
        measured = sum(segment_durations[:start])
        position = round(measured * finished_duration / original, 2)
        if position >= finished_duration:
            raise ValueError('Chapter beyond end of episode')
        result.append({'title': labels[i] if i < len(labels) else f'Part {i+1}',
                       'start_seconds': position})
    if len(set(x['start_seconds'] for x in result)) != len(result):
        raise ValueError('Overlapping chapters')
    return result


def verified_publish(staged_audio: Path, metadata: dict, episodes_dir: Path,
                     day: str, validator):
    """Verify staged pair, then publish. CI only commits after this succeeds."""
    if probe_audio(staged_audio) is None:
        raise RuntimeError('Staged MP3 validation failed: existing episode untouched')
    episodes_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.radio-verify-', dir=episodes_dir) as d:
        tmp = Path(d)
        (tmp / f'{day}.mp3').write_bytes(staged_audio.read_bytes())
        atomic_json(tmp / f'{day}.json', metadata)
        validator(day, base=tmp, probe=True)
        # Both files have passed the same production validation.
        os.replace(tmp / f'{day}.mp3', episodes_dir / f'{day}.mp3')
        os.replace(tmp / f'{day}.json', episodes_dir / f'{day}.json')
    print(f'Published verified episode {day}', flush=True)