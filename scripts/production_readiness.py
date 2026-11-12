"""Offline, fail-closed production gate and human-readable recovery diagnosis."""
import argparse
import datetime as dt
import html
import os
from pathlib import Path
import re
import subprocess

try:
    from scripts import rebuild_request, verify, work_script
except ModuleNotFoundError:
    import rebuild_request
    import verify
    import work_script

ROOT = Path(__file__).resolve().parents[1]
JST = dt.timezone(dt.timedelta(hours=9))


def resolve_date(requested='', now=None):
    today = (now or dt.datetime.now(JST)).astimezone(JST).date()
    if requested == '':
        return today.isoformat()
    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', requested):
        raise ValueError('broadcast_date must use YYYY-MM-DD')
    day = dt.date.fromisoformat(requested)
    if not today - dt.timedelta(days=6) <= day <= today:
        raise ValueError('broadcast_date must be today or one of the preceding six JST dates')
    return day.isoformat()


def diagnose(root, day, replace_existing=False):
    """Never synthesizes or modifies episodes; valid published pairs need no draft."""
    root = Path(root)
    try:
        replacement = replace_existing or rebuild_request.pending(
            day, root / '.github/rebuild-request.json', root / 'episodes')
    except (OSError, ValueError) as exc:
        return 'invalid_request', f'Fix the reviewed rebuild request on main: {exc}'
    if not replacement:
        try:
            verify.check_episode(day, base=root / 'episodes', probe=True)
            return 'already_published', 'Valid episode already exists. No synthesis or replacement needed.'
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, AttributeError, subprocess.SubprocessError):
            pass
    directory = root / 'drafts' / day
    missing = [name for name in ('script.json', 'review.json') if not (directory / name).is_file()]
    if missing:
        return 'missing_input', (f'Missing {", ".join(missing)}. Submit the exact independently reviewed '
                                 f'package under drafts/{day}/, pass validation, merge to main, then retry '
                                 'this date within the retention window.')
    try:
        prepared = work_script.load_submission(root, day)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return 'invalid_input', (f'Invalid or stale reviewed package: {exc}. Correct the script, obtain '
                                 'independent review of its exact hash, validate and merge to main, then retry.')
    return 'ready', (f'Reviewed script SHA-256: {prepared["script_hash"]}. Ready for synthesis and '
                     'audio validation; this is not confirmation of publication.')


def report(day, sha, status, detail):
    # Escape untrusted package error text instead of allowing summary markup injection.
    summary = ('## MASURADIO production readiness\n\n'
               f'Target broadcast date (JST): {html.escape(day)}\n\n'
               f'Checked main SHA: {html.escape(sha)}\n\n'
               f'Status: {status}\n\n{html.escape(detail)}\n\n'
               'Missing or invalid input stops before TTS, commit and publication. '
               'Existing broadcasts are preserved; no paid fallback runs.\n')
    print(summary)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
            stream.write(summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resolve-date', action='store_true')
    parser.add_argument('--date', default='')
    parser.add_argument('--replace-existing', action='store_true')
    args = parser.parse_args()
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if args.resolve_date:
        try:
            day = resolve_date(args.date)
        except ValueError as exc:
            report(args.date, sha, 'invalid_date', str(exc))
            return 1
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
                stream.write(f'today={day}\n')
        print(day)
        return 0
    # The workflow resolves and bounds the date once, before dependency installation.
    # Do not recompute JST today here: a queued run can cross midnight.
    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', args.date):
        report(args.date, sha, 'invalid_date', 'Resolve a strict broadcast date first.')
        return 1
    try:
        dt.date.fromisoformat(args.date)
    except ValueError as exc:
        report(args.date, sha, 'invalid_date', str(exc))
        return 1
    status, detail = diagnose(ROOT, args.date, args.replace_existing)
    report(args.date, sha, status, detail)
    if status not in ('ready', 'already_published'):
        return 1
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
            stream.write(f'ready={str(status == "already_published").lower()}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
