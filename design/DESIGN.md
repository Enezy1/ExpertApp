---
name: Adliya Judicial Intelligence
colors:
  surface: '#f7fafd'
  surface-dim: '#d7dadd'
  surface-bright: '#f7fafd'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f1f4f7'
  surface-container: '#ebeef1'
  surface-container-high: '#e5e8eb'
  surface-container-highest: '#e0e3e6'
  on-surface: '#181c1e'
  on-surface-variant: '#44474c'
  inverse-surface: '#2d3133'
  inverse-on-surface: '#eef1f4'
  outline: '#74777d'
  outline-variant: '#c4c6cc'
  surface-tint: '#525f71'
  primary: '#000000'
  on-primary: '#ffffff'
  primary-container: '#0f1c2c'
  on-primary-container: '#778598'
  inverse-primary: '#bac8dc'
  secondary: '#386380'
  on-secondary: '#ffffff'
  secondary-container: '#b2dcfe'
  on-secondary-container: '#37627f'
  tertiary: '#000000'
  on-tertiary: '#ffffff'
  tertiary-container: '#001e2d'
  on-tertiary-container: '#008dc3'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#d6e4f9'
  primary-fixed-dim: '#bac8dc'
  on-primary-fixed: '#0f1c2c'
  on-primary-fixed-variant: '#3a4859'
  secondary-fixed: '#c9e6ff'
  secondary-fixed-dim: '#a1cced'
  on-secondary-fixed: '#001e2f'
  on-secondary-fixed-variant: '#1d4b67'
  tertiary-fixed: '#c6e7ff'
  tertiary-fixed-dim: '#83cfff'
  on-tertiary-fixed: '#001e2d'
  on-tertiary-fixed-variant: '#004c6b'
  background: '#f7fafd'
  on-background: '#181c1e'
  surface-variant: '#e0e3e6'
typography:
  headline-xl:
    fontFamily: IBM Plex Sans
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 44px
  headline-xl-mobile:
    fontFamily: IBM Plex Sans
    fontSize: 24px
    fontWeight: '700'
    lineHeight: 34px
  headline-lg:
    fontFamily: IBM Plex Sans
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 36px
  headline-lg-mobile:
    fontFamily: IBM Plex Sans
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 30px
  headline-md:
    fontFamily: IBM Plex Sans
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 30px
  headline-sm:
    fontFamily: IBM Plex Sans
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 24px
  body-lg:
    fontFamily: IBM Plex Sans
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: IBM Plex Sans
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 24px
  body-sm:
    fontFamily: IBM Plex Sans
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 20px
  label-lg:
    fontFamily: IBM Plex Sans
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
  label-md:
    fontFamily: IBM Plex Sans
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 18px
  label-sm:
    fontFamily: IBM Plex Sans
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 16px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1.25rem
  margin: 2rem
  space-xs: 0.375rem
  space-sm: 0.75rem
  space-md: 1.25rem
  space-lg: 2rem
  space-xl: 3rem
---

## Brand & Style

This design system establishes an authoritative, sovereign, and ultra-contemporary enterprise interface tailored for judicial expert administration under the Ministry of Justice. The visual identity bridges institutional gravity with 21st-century digital efficiency, projecting uncompromising accuracy, procedural transparency, and legal finality.

The aesthetic fuses **Corporate High-Tech** with **Subtle Glassmorphism and Deep Layering**. Deep midnight navy anchors the structural hierarchy (representing sovereign weight and security), while luminous royal blue and electric cyan accents denote active states, digital verification, and forward momentum through complex casework. The visual posture is strictly Right-to-Left (RTL), engineered with crystalline legibility, rigorous information density, and deliberate procedural pacing.

## Colors

The palette balances executive sovereign gravitas with precise technological indicators:

- **Primary (`#0D1B2A`):** Deep Midnight Navy. Anchors persistent navigation sidebars, high-level headers, primary buttons, and structural boundaries.
- **Secondary (`#1B4965`):** Sovereign Slate Blue. Governs secondary containers, active navigational states, interactive tabs, and categorical accents.
- **Tertiary (`#00A8E8`):** Tech Cyan. Reserved for interactive feedback, step progression milestones, pending expert review indicators, and analytical highlights.
- **Neutral (`#F4F7FA`):** Crisp Architectural Slate. Serves as the overarching canvas surface, providing anti-glare reading comfort for exhaustive legal documentations and dossiers.

Supporting contextual tokens:
- **Surface Elevation:** `#FFFFFF` with translucent boundary borders (`rgba(13, 27, 42, 0.06)`).
- **Procedural Success (Legal Verification):** `#0E8A5E` (Deep Emerald).
- **Procedural Warning (Hearing Overdue / Deadline):** `#D97706` (Amber Bronze).
- **Legal Alert (Contested / Stay of Execution):** `#C52828` (Crimson Garnet).

## Typography

Typography is standardized on `IBM Plex Sans` (paired with the native IBM Plex Sans Arabic character set) to deliver geometric precision, high horizontal cadence, and formal administrative credibility. 

Typographic rules:
- **Baseline Alignment:** Strict baseline rhythm configured for elongated Arabic ligatures, preventing diacritic clipping and maintaining legibility in multi-tier case dockets.
- **Numerals:** Case numbers, court session dates, and civil registry IDs enforce tabular alignment (`tnum`) to eliminate layout jitter across data tables.
- **Hierarchy:** High weight contrasts (`700` and `600`) reserved exclusively for case statuses, litigant names, and stage anchors, while long legal narratives, findings, and technical opinions maintain generous line heights (`lineHeight: 28px` for 16px body) for eye tracking across broad display viewports.

## Layout & Spacing

The structural layout utilizes a persistent dual-pane operational model with a fluid-responsive content canvas:
- **Master Navigation Shelf:** Fixed width of `280px` on desktop pinned to the Right hand side (RTL), housing case categories, departmental divisions, and session queues.
- **Canvas Viewport:** 12-column responsive fluid grid spanning the remainder of the workspace, structured with `1.25rem` (20px) gutters and a bounding perimeter margin of `2rem` (32px).
- **Responsive Adaptations:**
  - **Desktop (>= 1280px):** Simultaneous timeline stepper header, multi-card case queue, and collapsible deep-inspection inspector panel on the left.
  - **Tablet (768px – 1279px):** Sidebar condenses into an icon-rail (`72px`), cards flow into single-column or 2-column configurations, timeline collapses into a scrollable horizontal pill sequence.
  - **Mobile (< 768px):** Navigation moves to an off-canvas drawer; top procedural stepper converts into a numerical fractional milestone (`خطوة 3 من 6`).

## Elevation & Depth

Depth in this system conveys administrative priority, separation of judicial proof, and tactical focus:

- **Level 0 (Base Canvas):** Solid architectural tint (`#F4F7FA`), devoid of shadows, hosting background structural columns.
- **Level 1 (Card & Section Containers):** Pure white `#FFFFFF` layered over the base canvas, framed by a delicate 1px border `rgba(13, 27, 42, 0.08)`. Subtle ambient shadow: `0 2px 8px -2px rgba(13, 27, 42, 0.04)`.
- **Level 2 (Active Case Dossier & Floating Modals):** Translucent frosted glass effect using `backdrop-filter: blur(16px)` with a pure white fill at 85% opacity (`rgba(255, 255, 255, 0.85)`) over dynamic graph and timeline data. Shadow: `0 12px 32px -4px rgba(13, 27, 42, 0.08), 0 4px 12px -2px rgba(13, 27, 42, 0.03)`.
- **Level 3 (Command Overlays, Signature Approvals & Action Trays):** High-density dark glass overlays (`rgba(13, 27, 42, 0.85)` with `backdrop-filter: blur(20px)`) or crisp elevated cards with `0 24px 48px -12px rgba(13, 27, 42, 0.18)`.

## Shapes

The geometric framework is calculated at Level 2 (Rounded), instilling executive refinement without sacrificing the disciplined architectural rigidity required by legal frameworks.

- **Primary Structural Containers & Case Panels:** `rounded-lg` (16px) corners to provide clean enclosing frames for legal data.
- **Buttons, Status Pills, and Badges:** `rounded-md` (8px) for precise, deliberate touch and click targets.
- **Timeline Nodes & Identity Avatars:** Complete geometric circles (`50%`) with high-contrast concentric inner boundary rings.
- **Data Dividers & Stage Connectors:** Crisp 2px linear geometries running seamlessly right-to-left.

## Components

### 1. Interactive Procedural Stepper (مسار التقرير)
The report workflow engine guides the expert through the canonical judicial progression:
`(الموضوع) -> (المأمورية) -> (الإجراءات) -> (البحث ورأي الخبرة) -> (النتيجة) -> (المرفقات)`
- **Node Geometry:** Numbered circular badges connected by a continuous 2px baseline bar.
- **States:**
  - *Completed:* Solid Midnight Navy with Tech Cyan icon tick mark; connecting rail turns solid Cyan.
  - *Active:* Tech Cyan ring pulse (`box-shadow: 0 0 0 4px rgba(0, 168, 232, 0.18)`), bold typography, elevated surface pill.
  - *Upcoming:* Low-contrast muted slate ring (`#CBD5E1`) with subtle neutral fill.

### 2. Case Dossier Smart Cards (بطاقات القضايا الذكية)
- **Structure:** Clean white surface container with a 4px vertical legal priority indicator on the inner right edge (RTL):
  - Emergency / Incarceration: Crimson
  - Priority Telecom / Banking: Tech Cyan
  - Regular Session: Slate Navy
- **Meta Hierarchy:** Top line displays tabular case code (`A2260621`) and receiving date badge; middle line contains stylized full litigant names and corporate entities; bottom row displays active tags, company chips (e.g., `زين`, `stc`), and quick-action icon trays (طباعة، معاينة، إحالة).

### 3. Action Buttons & Controls
- **Primary Action (اعتماد التقرير / إضافة قضية):** Solid `#0D1B2A` with `#FFFFFF` text, subtle 1px border highlight `rgba(255, 255, 255, 0.1)`, shifting to `#1B4965` on hover with crisp 150ms transitions.
- **Secondary Action (تحديث الجلسات / تصفية):** Transparent background with `1px solid rgba(13, 27, 42, 0.15)` border and `#0D1B2A` label, elevating to Level 1 shadow on hover.
- **Affirmative Action:** Tech Cyan fill with white text, used strictly for procedural submissions and final sign-offs.

### 4. Categorical Badges & Filtering Chips
- Micro-pill design with `8px` corner radius and `6px 14px` padding.
- Semi-transparent background fills: `rgba(0, 168, 232, 0.08)` for informational tags; `rgba(13, 27, 42, 0.06)` for neutral entity markers.

### 5. Input Fields & Judicial Form Elements
- Inputs feature high-legibility paddings (`12px 16px`), light grey neutral borders (`#E2E8F0`), and crisp RTL placeholder alignments.
- Active focus invokes a 2px Tech Cyan boundary ring (`#00A8E8`) with zero layout shift.