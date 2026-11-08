---
target: qt_referred_page_v2.py
total_score: 25
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 3
target_identity: "file:C:\\Users\\Dell\\Desktop\\ExpertApp\\qt_referred_page_v2.py"
target_fingerprint: "sha256:8a9f3a3f99879db2fbae6a57d714096e2aff38425b8c573bfd35288c2c622698"
target_path: "C:\\Users\\Dell\\Desktop\\ExpertApp\\qt_referred_page_v2.py"
timestamp: 2026-10-04T12-40-03Z
slug: qt-referred-page-v2-py
---
# Critique: qt_referred_page_v2.py — 25/40 (Acceptable)
Scores: 2,3,2,2,3,3,2,3,3,2. Specificity: authored (incoming memo, fact boxes).
## Priority issues
- [P1] No in-flight state during irreversible submit (harden; threading = logic)
- [P1] Confirmation Yes/No, emoji, no accept consequence, case no. not LTR (clarify; logic)
- [P1] Card lacks triage info: age, type, urgency buried in notes (layout; new fields = logic)
- [P2] Secondment red ~ danger red; red '0' KPI (colorize)
- [P2] Redundant KPI strip; full reload + modal per action (distill)

## Cross-cutting (detector + contrast)
- TEXT_MUTED #94A3B8 = 2.45:1 on BG (fails 3:1) — used for real text in all pages.
- EMERALD #1D9E75 small text (11px) = 3.2:1 (fails 4.5:1): now-line, deadline caption, status.
- Detector: 13 advisory findings, no anti-patterns (pill radius 9px duplicated x3, 8px menu item, 15px chip, 14px placeholder).
- Keyboard focus ring not implemented (deferred; needs qt_widgets line).
