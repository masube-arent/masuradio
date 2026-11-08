# MASURADIO 88.8

AI-assisted development radio. Daily Japanese MP3 show using Gemini and edge-tts, hosted on GitHub Pages.

Setup: Add `GEMINI_API_KEY` in Settings > Secrets and variables > Actions, enable GitHub Pages (GitHub Actions), then run the Daily Radio workflow.

Reliability: A separate `Validate MASURADIO` workflow checks Python, unit tests and player JavaScript on code changes. The daily workflow retries temporary Gemini failures, validates MP3/JSON integrity, and preserves complete audio even when a show runs outside the preferred 10–20 minutes. Publish validates the archive before deployment. Scheduled broadcasts use concurrency protection and retry Git push conflicts.

Limits: `edge-tts` is an unofficial external service; outages, missing API credit, GitHub scheduler delays or permissions errors can still prevent a broadcast. A failed generation should remain a failure rather than reporting a false success. Audio, sources and scripts are public. No billing fallback is configured.

Editorial diversity: 7 distinct weekday pillars (models/research, useful AI apps, automation/agents, audio/video/images, safety/cost, playful experiments, and real-world impact). Official RSS feeds cover multiple AI publishers. Prereleases are filtered, stories are distributed across publishers, and recently featured source URLs are deprioritized. Different program parts use different article sets to avoid repeating the same story.

Voice format: NANA is the only host, synthesized with `ja-JP-NanamiNeural` at normal speaking speed. Gemini writes a solo monologue with occasional natural self-banter (ひとりノリツッコミ), without co-hosts or other voices. Older episodes retain their original three-DJ audio.

Pronunciation: a speech-only dictionary converts `Claude Code`, `ClaudeCode`, and common variants to the Japanese reading `クロードコード` before edge-tts. Source scripts and published metadata retain original English spellings; previously published MP3s are not changed automatically.

Gemini output cutoff protection: On Gemini 2.5 Flash the first pass uses a 512-token thinking budget, and JSON recovery attempts disable thinking and use 12,288 output tokens. This prevents hidden thinking from using the full response budget. Updating the generator automatically triggers a daily recovery run, which skips the episode if it is already valid.

Evidence and resume (2026-11):
- Feed URLs are normalized and same-event sources combined conservatively.
- At most seven articles are fetched with timeouts, robots checks and HTTPS limits.
- Only body-confirmed excerpts can ground detailed discussion; headline-only claims stay labeled.
- Published source JSON excludes extracted article excerpts.
- Feed, scripts, TTS, merged audio reuse .radio-cache and GitHub Actions cache.
- Chapter times use measured audio segment durations; older episodes have no chapters.
- Playback position is saved per episode on-device; no automatic archive playback.
- QA: python -m unittest discover -s tests -v; node tests/test_playback.cjs.

Editorial grounding (2026-11-08 proposal):
- Preserve complete article paragraphs, including later numerical qualifiers and developer/license/language context, within 8 excerpts / 6,000 characters per article. Oversized paragraphs are skipped, never sliced mid-claim.
- Keep article publication metadata separate from RSS dates; conflicting publication metadata remains unknown. Publisher/platform never implicitly becomes the developer.
- Assign reporting stories once, pass the preceding script into later chapters, and give the practical chapter a verified source. If no article body is available, shorten the show and use a clearly labeled source-checking exercise.
- Require exact excerpt references for factual claims and spoken target/action/success/stop criteria for practice. Deterministic checks reject missing evidence, uncited report numbers, repeated introductions and substantial repeated sentences. These checks cannot establish semantic truth by themselves.
- Before TTS, one additional Gemini call audits the full script against the evidence (including omitted claims, metric meanings/comparisons, attribution, dates, duplication and usefulness). It uses the same configured model, temperature 0.1, 512 thinking tokens and at most 4,096 output tokens. Semantic review reduces risk but is not a factual guarantee.
- Rejection, incomplete or malformed audit output stops generation before audio/publication. Valid audit decisions, including rejections, are cached so unchanged rejected drafts do not spend another audit call on scheduled retries. Correct the draft inputs or editorial code before retrying; this does not automatically repair rejected drafts.
- Expanded evidence/context increases input tokens; the audit adds one normal API call per new draft (existing transport retries still apply). Usage estimates include the audit, using the existing illustrative Flash rates; they are not a billing cap. No paid generation is required for the offline regression suite.

Rollout: review the draft PR and passing validation before merging. A main-branch change to `scripts/generate.py` automatically starts Daily MASURADIO recovery and Pages workflows; recovery skips a currently valid episode. Do not merge or dispatch generation just to run these offline tests. Existing published audio/JSON are not rewritten by this change.
