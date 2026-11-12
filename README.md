# MASURADIO 88.8

Japanese AI/DX radio hosted on GitHub Pages. Work researches public primary sources and writes a reviewed NANA script; GitHub Actions validates, synthesizes with edge-tts, and publishes it.

Current setup: GitHub Pages uses GitHub Actions. Submit `drafts/YYYY-MM-DD/script.json` and its independent, hash-bound `review.json` through a reviewed PR. Merging to main triggers audio generation and publication for today's JST date. See [Work production workflow](editorial/WORKFLOW.md). The daily production workflow no longer calls Gemini or needs its API key; the old writer remains available only as legacy code, not as an automatic fallback.

Reliability: `Validate MASURADIO` checks Python, unit tests, player JavaScript, and every submitted script/review without paid calls. Production pins one JST date, requires reviewed input before TTS, validates the MP3/JSON pair, and preserves complete audio even outside the preferred 10–20 minutes. Publish validates the archive before deployment. Concurrency protection, input hashes, and completed-episode checks prevent duplicate generation; missing input or a failed check preserves older broadcasts.

Limits: `edge-tts` is an unofficial external service; outages, delayed/missing Work input, GitHub scheduler delays, or permissions errors can prevent a broadcast. Failures remain failures rather than false success. Audio, scripts, submitted excerpts, review records, and source notes are public. Use public information and short permissible quotations only. Work consumes its own plan allowance. No paid fallback is configured. GitHub cron renders an already supplied script; it does not itself launch ChatGPT Work research. Schedule that producer separately and verify its first runs.

Current editorial format (2026-11-10): verified news followed by one clearly labeled DX proposal with a target, action, observable check, and stop condition. Factual prerequisites need evidence; proposed benefits are not measured outcomes. NANA remains at the existing normal synthesis speed. Playback-speed feedback did not change the audio rate.

The sections below record the earlier Gemini pipeline and its retained offline contracts. They are historical where they refer to automated Gemini writing/auditing. New Work submissions receive independent source/content review before merge instead, and still pass the deterministic citation, number, coverage, and continuity checks.

Editorial diversity: 7 distinct weekday pillars (models/research, useful AI apps, automation/agents, audio/video/images, safety/cost, playful experiments, and real-world impact). Official RSS feeds cover multiple AI publishers. Prereleases are filtered, stories are distributed across publishers, and recently featured source URLs are deprioritized. Each verified story is reported once. Weekday pillars guide selection, but the spoken theme and title follow the available evidence.

Voice format: NANA is the only host, synthesized with `ja-JP-NanamiNeural` at normal speaking speed. Gemini writes a solo monologue with occasional natural self-banter (ひとりノリツッコミ), without co-hosts or other voices. Older episodes retain their original three-DJ audio.

Pronunciation: a speech-only dictionary converts `Claude Code`, `ClaudeCode`, and common variants to the Japanese reading `クロードコード` before edge-tts. Source scripts and published metadata retain original English spellings; previously published MP3s are not changed automatically.

Gemini output cutoff protection: On Gemini 2.5 Flash the first pass uses a 512-token thinking budget, and JSON recovery attempts disable thinking and use 12,288 output tokens. This prevents hidden thinking from using the full response budget. Updating the generator automatically triggers a daily recovery run, which skips the episode if it is already valid.

Evidence and resume (2026-11):
- Feed URLs are normalized and same-event sources combined conservatively.
- At most seven articles are fetched with timeouts, robots checks and HTTPS limits.
- Only body-confirmed excerpts can ground the broadcast; unavailable headlines are not read as filler.
- Published source JSON excludes extracted article excerpts.
- Feed, scripts, TTS, merged audio reuse .radio-cache and GitHub Actions cache.
- Chapter times use measured audio segment durations; older episodes have no chapters.
- Playback position is saved per episode on-device; no automatic archive playback.
- QA: python -m unittest discover -s tests -v; node tests/test_playback.cjs.

Editorial grounding (2026-11-08, updated 2026-11-09):
- Preserve complete article paragraphs, including later numerical qualifiers and developer/license/language context, within 8 excerpts / 6,000 characters per article. Oversized paragraphs are skipped, never sliced mid-claim.
- Keep article publication metadata separate from RSS dates; conflicting publication metadata remains unknown. Publisher/platform never implicitly becomes the developer.
- Assign reporting stories once and pass the preceding script into later chapters. Current production uses verified reporting only, with no compulsory practical chapter or source-checking filler; no verified body stops generation before paid writing.
- Require exact excerpt references for factual claims and spoken target/action/success/stop criteria for practice. Deterministic checks reject missing evidence, uncited report numbers, repeated introductions and substantial repeated sentences. These checks cannot establish semantic truth by themselves.
- Before TTS, one additional Gemini call audits the full script against the evidence (including omitted claims, metric meanings/comparisons, attribution, dates, duplication and usefulness). It uses the same configured model, temperature 0.1, 512 thinking tokens and at most 4,096 output tokens. Semantic review reduces risk but is not a factual guarantee.
- Rejection, incomplete or malformed audit output stops generation before audio/publication. Valid audit decisions, including rejections, are cached so unchanged rejected drafts do not spend another audit call on scheduled retries. Correct the draft inputs or editorial code before retrying; this does not automatically repair rejected drafts.
- Expanded evidence/context increases input tokens; the audit adds one normal API call per new draft (existing transport retries still apply). Usage estimates include the audit, using the existing illustrative Flash rates; they are not a billing cap. No paid generation is required for the offline regression suite.

Earlier headline-only recovery (2026-11-09, superseded in production by verified-only news):
- The headline-only opening now uses a short, fixed NANA template with explicit unverified framing and an empty claim ledger. It makes no Gemini writing call, never invents excerpt IDs, and skips unusable/oversized titles rather than cutting them into new claims.
- Body reporting and practice still use Gemini, exact evidence validation, and the full semantic audit before speech. The fixed opening is included in that audit too; an audit rejection still prevents audio/publication.
- Script cache keys include the editorial version so older generated openings are not reused after this fix. Feed and article-evidence caches can still resume normally.

Continuation recovery (2026-11-09):
- Later chapters still reject repeated audience greetings and host introductions. A greeting inside paired quotes is allowed only with nearby, unquoted sample/input framing; a final practice farewell may name the station.
- Rejections identify the chapter, zero-based segment index and a fixed marker category, without logging arbitrary draft/article text. The same bounded retry receives that diagnostic.
- Only the practice prompt changes, so already validated opening/report chapters can resume from cache. The full semantic audit still runs before any new audio/publication.

Rollout: review the draft PR and passing validation before merging. A main-branch change to `scripts/generate.py` automatically starts Daily MASURADIO recovery and Pages workflows; recovery skips a currently valid episode. Do not merge or dispatch generation just to run these offline tests. Existing published audio/JSON are not rewritten by this change.


Information-value revision (2026-11-09):
- Report up to five distinct body-confirmed stories, at most two per chapter. Do not read unverified English headlines, invent a daily theme, add a mandatory exercise, repeat stories, or pad to a duration.
- Every assigned story needs at least two distinct spoken fact segments, each bound to an exact excerpt from its own source. The full semantic audit checks actual Japanese meaning, novelty and useful detail, not just valid citation IDs. Conditions such as preview status, version, product surface and eligibility must be preserved when material.
- Capability announcements do not establish productivity gains. Navigation such as “Install Copilot CLI” is not a new release, and a command under a CLI heading must retain that scope. Prompts and the audit explicitly cover these failures from the November 9 episode.
- Extract complete paragraphs and article/release lists with section context. Download size is bounded at 2 MB to accommodate official sites' application shells; retained excerpts still have the 8-excerpt / 6,000-character cap. HTTPS, per-redirect robots checks, stream limits and timeouts remain enforced. Fetch failures use fixed diagnostic reasons instead of only `ValueError`.
- Evidence and editorial cache versions change, so previously incomplete extraction and low-value drafts are not reused. An empty feed snapshot or zero-body fetch result is not cached, so a later scheduled retry can recover after a temporary outage. Successful partial-body stages still resume normally; unavailable sources in that cached partial result are not automatically refreshed. Featured sources and topics reflect the stories actually reported.
- The optional workflow-dispatch `replace_existing` input defaults to false. Ordinary merges, scheduled runs and manual runs still skip a valid episode. An explicitly requested replacement reuses valid cached stages when unchanged, may incur Gemini usage, creates a complete audio/JSON pair before replacing anything, and is published only after validation. Do not enable it without authorization to replace today's public episode and incur the API usage.
- Offline validation does not call Gemini or TTS. The new writer/audit behavior still requires a real generation to assess editorial quality; passing tests alone is not proof that generated prose is accurate or useful.


Authorized one-time rebuilds:
- A reviewed `.github/rebuild-request.json` can request a rebuild for one JST date without browser login. The file contains only `date` and a unique `request_id`.
- A matching request is pending until a successfully validated/published episode records that ID. Queued runs refresh main under the existing concurrency group, then skip the consumed request. Failures preserve the old episode and may resume cached stages on retry.
- Requests for a past or future date do not replace today's valid episode. The November 9 quality replacement expires after November 9 and does not change ordinary daily behavior.
- Creating a new request still requires authorization to replace that public episode and incur Gemini usage. No credentials or expanded GitHub permissions are added.


Citation transport recovery (2026-11-09):
- The writer selects short chapter-local excerpt IDs instead of retyping long source quotes. Code validates each reference and binds it to the original exact, complete excerpt; the semantic audit sees the original source IDs and text.
- Unknown or malformed references and incorrect explicit legacy quotes still fail. Per-story source binding, numerical checks and the full meaning/usefulness audit remain required; reference validity alone does not prove a claim.
- Writer temperature is 0.3 for factual reporting. Citation and numeral failures provide fixed diagnostic categories and claim or segment positions without logging arbitrary rejected draft text.


Numeric retry recovery (2026-11-09):
- Exact per-segment numeric evidence checks remain unchanged. Titles, feed metadata and version labels outside the cited article excerpts do not establish support. Writers must preserve the excerpt's numeric notation or omit the unsupported number.
- Numeric rejection now returns the affected sentence and bounded repair context to the same writer request, because API retries do not remember earlier drafts. Numeric rejection logs retain only positions and fixed diagnostic categories; rejected speech, arbitrary values and repair context are not logged.
- Valid citations, per-story coverage and the complete semantic audit remain mandatory before TTS and publication. This is targeted repair feedback, not automatic rewriting or acceptance of missing evidence.

Production recovery (2026-11-12): validation runs are grouped per PR so a newer run supersedes older checks. A long queue is not a test pass. Daily production reports its fixed JST date, checked main SHA, and whether input is ready, missing, invalid, or already published; missing review still stops before audio. Explicit manual recovery can select today or one of the previous six JST dates. Cache availability is optional, but generation/verification/commit success is not. Pages publication now verifies the live archive JSON and MP3 bytes against its artifact before reporting success. Same-script rebuild requests are consumed without duplicate synthesis. External queue, network, and TTS outages can still delay publication; see [the recovery procedure](editorial/WORKFLOW.md#recovery-and-delivery-checks-2026-11-12).
