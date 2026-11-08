---
target: qt_pending_page_v2.py
total_score: 25
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 3
target_identity: "file:C:\\Users\\Dell\\Desktop\\ExpertApp\\qt_pending_page_v2.py"
target_fingerprint: "sha256:df8e8b36f7956a2a7d6256305a904c82222ea4eaa1b24ca800eb3ae69145d65c"
target_path: "C:\\Users\\Dell\\Desktop\\ExpertApp\\qt_pending_page_v2.py"
timestamp: 2026-10-04T12-40-03Z
slug: qt-pending-page-v2-py
---
# Critique: qt_pending_page_v2.py — 25/40 (Acceptable)
Scores: 3,3,2,3,3,2,2,3,2,2. Specificity: authored (21-tick ruler, urgency-first).
## Priority issues
- [P1] Due date only in tooltip; fix Arabic plurals (clarify)
- [P1] KPI row duplicates chips; pushes content; shows 0 on error (distill)
- [P1] Contrast: emerald 11px on blue card ~3:1; unfilled ruler ticks ~1.05:1; muted subline 2.5:1 (audit/harden)
- [P2] Raw exception text in error view; stale counts on error (harden)
- [P2] Same navy primary on every card, wrong lead for reserved cases (layout)

## Cross-cutting (detector + contrast)
- TEXT_MUTED #94A3B8 = 2.45:1 on BG (fails 3:1) — used for real text in all pages.
- EMERALD #1D9E75 small text (11px) = 3.2:1 (fails 4.5:1): now-line, deadline caption, status.
- Detector: 13 advisory findings, no anti-patterns (pill radius 9px duplicated x3, 8px menu item, 15px chip, 14px placeholder).
- Keyboard focus ring not implemented (deferred; needs qt_widgets line).
