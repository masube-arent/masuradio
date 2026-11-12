# 2026-11-13 MASURADIO source notes

Public sources only. Broadcast date is Japan time; research performed on 2026-11-12 UTC. No private work or messages used. This file records writer checks, not independent approval.

## Reports

- https://github.blog/changelog/2026-11-10-gemini-4-carbon-in-github-copilot/
  - Opened full official article. Published November 10, 2026, not a November 13 launch.
  - General availability, gradual rollout, Pro+/Max/Business/Enterprise eligibility, provider-list usage billing, and administrative model policy checked against body.
  - No benchmark, superiority, token price, or savings claim. The pricing clarification is an explanation of usage billing, not a quote claiming every account incurs an extra charge.
- https://github.blog/changelog/2026-11-12-public-monitoring-alerts-now-have-direct-links/
  - Opened full official article. Published November 12, 2026.
  - Individual alert URL, opening from alert number, bookmarks, sharing only with teammates with access, Enterprise Cloud plus Secret Protection/Advanced Security eligibility, and no additional charge within that scope checked against body.
  - No claim of public access, new permission grants, or automatic remediation.

## DX proposal (revised after independent review)

Concrete idempotency exercise rather than another intake/handoff checklist. Synthetic IDs and fixed ordered update times are used as event keys, while the current work-ticket table is keyed only by ID. Test duplicate delivery, identical display name with different IDs, stale delivery including a stale event absent from the receipt log, repeated full input, and conflicting payload under an identical key. Expected states are explicit. This is a proposed toy protocol, not a claim about GitHub webhook identifiers or delivery semantics. Real integration requires separately verifying identifier uniqueness and time semantics. No actual warning values, URLs, credentials, or external writes are used.

## Repetition check

Compared draft packages for November 10–12: Workspace skills/weekly report, Actions-log scanning, Drive labels; C++ build setup/Claude connected apps/change acceptance tests; personal Issue fields, Workspace MCP authentication deadline, Dependabot inactivity/Issue intake. Today's model eligibility and event-idempotency simulation is distinct; the previous intake/fact-preservation exercise was specifically replaced after review. Did not re-report the November 9 Actions-log scanning update. Existing earlier archive titles also checked.

## Local structural check

`load_submission('.', '2026-11-13', require_review=False)` passes. Independent reviewer must reopen both sources and review every speech segment before writing review.json. No reviewer approval has been created by the writer.
