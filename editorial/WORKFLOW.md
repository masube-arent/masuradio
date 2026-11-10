# Work-to-MASURADIO production

## Responsibilities and trust

Work performs source research, drafting, and independent editorial review. GitHub receives a reviewed package and performs deterministic validation, NANA speech synthesis, audio validation, and publication. This route makes no Gemini API calls. Do not claim it is free: Work consumes its own allowance and external-service conditions can change.

Only public information may enter this public repository. Do not use private Slack, Drive, email, company projects, personal data, credentials, full articles, or long source excerpts. PRs, commits, logs, and caches are not private storage. A publisher name or a search snippet is not sufficient evidence.

The security boundary is the maintainer-controlled main branch and its merge process. `review.json` is a version-bound editorial record, not a cryptographic signature, a factual guarantee, or authority to publish untrusted third-party input. A writer must not approve its own draft. A separate reviewer must actually open the primary sources and examine every spoken claim, including uncited claims. Merge only after the exact final payload is reviewed and CI passes. If any payload field changes, obtain a new review.

## Package files

For the JST broadcast date, submit:

- `drafts/YYYY-MM-DD/script.json`: schema version 1, ISO broadcast date, `Asia/Tokyo`, unique script id, short Japanese episode title, and ordered chapters.
- `drafts/YYYY-MM-DD/review.json`: exact canonical script SHA-256, independent review method, timezone-qualified review time, approved decision, full checklist, and no unresolved issues.
- Optionally `source-notes.md`: public source links and concise verification notes; no long quotations.

See `drafts/2026-11-10/script.json` for a complete example and `scripts/work_script.py` for the executable contract. Input size is limited to 128 KB. Source URLs must be public HTTPS publisher URLs without credentials; dates and timezone-qualified retrieval timestamps are explicit. Article publication dates may be null. Do not treat retrieval or feed dates as release dates.

Use one to three reporting chapters followed by exactly one DX chapter. Reports have one or two distinct sources each, with at most five reporting sources overall. Each source needs two distinct useful fact segments, each bound to an excerpt from that source. All chapters have 2-9 NANA segments, each 5-500 characters. Report facts must preserve the cited number's exact notation, scope, prerequisites, eligibility, and restrictions.

Citation aliases such as `S1E1` are local to each chapter's ordered sources and excerpts. Do not invent IDs or copy arbitrary quotes into the claim ledger. Use short faithful excerpts within permissible quotation limits, preserve the source's conditions in the narration, and review the full primary page independently. An excerpt match does not establish that the Japanese paraphrase is true.

The final `practice` chapter must explicitly say `ここからは番組の活用提案です。` and speak four distinct `practice` strings: `target`, `action`, `check`, and `stop`. Mark suggestions as suggestions. Cite factual product prerequisites. Use harmless public or synthetic sample data; do not instruct listeners to upload confidential work. Do not claim unmeasured productivity gains. Do not add generic exercises or repeat the news just to reach a duration.

## Verification before merge

1. Draft using opened primary sources and compare recent episodes for repetition.
2. Run `.venv/bin/python scripts/work_script.py --date YYYY-MM-DD` after the independent review record is created. A normal CI environment uses `python` instead of the local venv path.
3. Run `python -m unittest discover -s tests -v`, `node tests/test_playback.cjs`, Python compilation, player syntax checks, and `git diff --check`.
4. Open a date-scoped PR, wait for `Validate MASURADIO` on its exact final head, then merge the reviewed package.

The review checklist is defined by `REVIEW_CHECKS` in `scripts/work_script.py`. Compute the hash with `work_script.digest(parsed_script)`: UTF-8 canonical JSON, sorted keys, compact separators, no NaN. It binds both speech and evidence, not just the prose.

## Generation and publication

`Daily MASURADIO` runs only for main. A main push changing scripts, daily workflow, rebuild request, or submitted drafts triggers it. It refreshes main under the existing global concurrency group and fixes the JST date once. If a valid broadcast already exists, ordinary runs skip it. Otherwise today's script and review must both exist and validate before any TTS call.

`python scripts/publish_work.py --date YYYY-MM-DD` imports the reviewed package, reuses audio stages keyed by exact speech/voice/rate, produces measured chapter offsets, and validates the new MP3/JSON pair before making it available for the workflow commit. Episode metadata records the script hash and review time. Only finished episode files are committed.

`Publish MASURADIO` runs after successful main generation and validates the archive before Pages deployment. A code/draft merge may also publish the existing archive first; do not call the new broadcast delivered until the subsequent generation and Pages run both succeed and the live episode JSON/audio match the expected date and hash.

## Retries, replacement, and scheduling

- Existing valid same-date broadcast: no implicit replacement. Use the explicit manual replacement input or a reviewed date-specific rebuild request only when replacement is authorized.
- Same completed script hash: no repeated synthesis. Same-day different script: reject unless replacement is explicit.
- Missing, malformed, stale-review, or rejected input: fail before audio; preserve the old site. There is no automatic Gemini writing or paid fallback.
- TTS failure: incomplete audio is not published; a later retry can reuse completed segments.
- Pages failure after a successful episode commit: retry publication, not research or synthesis.
- The retained GitHub fallback times are 06:10, 08:10, and 11:10 JST. They are best-effort checks for already reviewed input, not a guarantee of broadcast timing.
- Schedule the separate Work producer early enough to prepare and independently review today's package before the desired release. The producer should first check whether that date is already published, then reuse an existing date-scoped PR rather than creating duplicates. Its recurring permission scope should be public research, script/review submissions, CI review, and publication, without code changes, credentials, new subscriptions, or private-source access.
- GitHub cron cannot initiate a Work session by itself. Do not describe daily Work research as configured until its separate scheduled task has been created and verified.

Keep legacy Gemini recovery changes separate. Neither an absent Work draft nor a rejected Work review authorizes a billing fallback.
