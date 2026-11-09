# MASURADIO 88.8

AI-assisted development radio. Daily Japanese MP3 show using Gemini and edge-tts, hosted on GitHub Pages.

Setup: Add `GEMINI_API_KEY` in Settings > Secrets and variables > Actions, enable GitHub Pages (GitHub Actions), then run the Daily Radio workflow.

Reliability: A separate `Validate MASURADIO` workflow checks Python, unit tests and player JavaScript on code changes. The daily workflow retries temporary Gemini failures, validates MP3/JSON integrity, and preserves complete audio even when a show runs outside the preferred 10–20 minutes. Publish validates the archive before deployment. Scheduled broadcasts use concurrency protection and retry Git push conflicts.

Limits: `edge-tts` is an unofficial external service; outages, missing API credit, GitHub scheduler delays or permissions errors can still prevent a broadcast. A failed generation should remain a failure rather than reporting a false success. Audio, sources and scripts are public. No billing fallback is configured.

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
