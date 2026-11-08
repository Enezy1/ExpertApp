---
target: qt_sessions_page.py
total_score: 25
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 3
target_identity: "file:C:\\Users\\Dell\\Desktop\\ExpertApp\\qt_sessions_page.py"
target_fingerprint: "sha256:2386544c6c984274eca3e8be502d9879ef53e0cc353015f1c55ed8708996a8c8"
target_path: "C:\\Users\\Dell\\Desktop\\ExpertApp\\qt_sessions_page.py"
timestamp: 2026-10-04T12-40-03Z
slug: qt-sessions-page-py
---
# Critique: qt_sessions_page.py — 25/40 (Acceptable; was 20/40)
| # | Heuristic | Score |
|---|---|---|
| 1 | Visibility of status | 3 |
| 2 | Match real world | 4 |
| 3 | User control | 2 |
| 4 | Consistency | 2 |
| 5 | Error prevention | 2 |
| 6 | Recognition | 3 |
| 7 | Flexibility | 2 |
| 8 | Aesthetic | 3 |
| 9 | Error recovery | 2 |
| 10 | Help | 2 |
Specificity: authored (ledger rail, day chapters, now-line, seal, greeting).
## Priority issues
- [P1] Compact mode (<760px): week-strip numerals clipped in 62px tiles; KPI row + strip + drawer leave ~1.5 cards. (adapt)
- [P1] Error/no-login states show false KPIs (0, emerald '—'); no-login has no action. (harden, display-only)
- [P1] Print button unchanged when today's محضر exists; re-print silently overwrites (business logic). (harden)
- [P2] Mouse-only: day tiles, drawer header, connection KPI. (harden)
- [P2] Print flow: UI freeze + modal; load-next-week no-op (logic). (clarify)

## Cross-cutting (detector + contrast)
- TEXT_MUTED #94A3B8 = 2.45:1 on BG (fails 3:1) — used for real text in all pages.
- EMERALD #1D9E75 small text (11px) = 3.2:1 (fails 4.5:1): now-line, deadline caption, status.
- Detector: 13 advisory findings, no anti-patterns (pill radius 9px duplicated x3, 8px menu item, 15px chip, 14px placeholder).
- Keyboard focus ring not implemented (deferred; needs qt_widgets line).
