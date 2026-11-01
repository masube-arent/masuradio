# MASURADIO 88.8

AI-assisted development radio. Daily Japanese MP3 show using Gemini and edge-tts, hosted on GitHub Pages.

Setup: Add `GEMINI_API_KEY` in Settings > Secrets and variables > Actions, enable GitHub Pages (GitHub Actions), then run the Daily Radio workflow.

Reliability: A separate `Validate MASURADIO` workflow checks Python, unit tests and player JavaScript on code changes. The daily workflow retries temporary Gemini failures, validates MP3/JSON integrity, and preserves complete audio even when a show runs outside the preferred 10–20 minutes. Publish validates the archive before deployment. Scheduled broadcasts use concurrency protection and retry Git push conflicts.

Limits: `edge-tts` is an unofficial external service; outages, missing API credit, GitHub scheduler delays or permissions errors can still prevent a broadcast. A failed generation should remain a failure rather than reporting a false success. Audio, sources and scripts are public. No billing fallback is configured.
