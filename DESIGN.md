---
name: نظام الخبراء — ExpertApp
description: A calm, right-to-left Arabic workspace for court experts, with navy ink on warm paper and emerald marking what is done.
colors:
  ledger-paper: "#FAFAF8"
  card-white: "#FFFFFF"
  paper-edge: "#EDEAE2"
  paper-edge-soft: "#F1EEE6"
  ink: "#0F172A"
  slate: "#475569"
  muted: "#94A3B8"
  chambers-navy: "#0F2747"
  chambers-navy-hover: "#153560"
  chambers-navy-pressed: "#0A1C34"
  navy-mist: "#F1F6F4"
  navy-tint: "#E8EDF4"
  rail-line: "#C9D3E0"
  sidebar-text-muted: "#93A5C2"
  seal-emerald: "#1D9E75"
  seal-emerald-hover: "#178A63"
  seal-emerald-bg: "#E1F5EE"
  seal-emerald-text: "#085041"
  emerald-on-navy: "#3FC79A"
  deadline-amber: "#B45309"
  deadline-amber-bg: "#FAEEDA"
  deadline-amber-text: "#854F0B"
  overdue-crimson: "#B42318"
  overdue-crimson-bg: "#FBEAE9"
  overdue-crimson-text: "#7A231C"
  danger-on-navy: "#F4A39B"
  info-blue-bg: "#EAF4FC"
  info-blue-text: "#0C447C"
  info-border: "#CFE4F4"
  secondment-blush: "#FDF2F6"
  secondment-red: "#C0392B"
  ruler-track: "#78859A"
  disabled-steel: "#B9C2CE"
  login-field: "#0F1D30"
  login-field-border: "#24344C"
  emerald-disabled: "#2E4A42"
  emerald-disabled-text: "#B7C3BF"
typography:
  hero:
    fontFamily: "Tajawal, Segoe UI, sans-serif"
    fontSize: "28px"
    fontWeight: 800
  display:
    fontFamily: "Tajawal, Segoe UI, sans-serif"
    fontSize: "22px"
    fontWeight: 700
  headline:
    fontFamily: "Tajawal, Segoe UI, sans-serif"
    fontSize: "20px"
    fontWeight: 700
  title:
    fontFamily: "Tajawal, Segoe UI, sans-serif"
    fontSize: "15px"
    fontWeight: 500
  nav:
    fontFamily: "Tajawal, Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 500
  body:
    fontFamily: "Tajawal, Segoe UI, sans-serif"
    fontSize: "13px"
    fontWeight: 400
  label:
    fontFamily: "Tajawal, Segoe UI, sans-serif"
    fontSize: "12px"
    fontWeight: 400
  caption:
    fontFamily: "Tajawal, Segoe UI, sans-serif"
    fontSize: "11px"
    fontWeight: 700
rounded:
  bar: "3px"
  tooltip: "6px"
  menu-item: "8px"
  mini-pill: "9px"
  control: "10px"
  block: "12px"
  chip: "15px"
  card: "16px"
  pill: "20px"
spacing:
  xxs: "4px"
  xs: "6px"
  sm: "10px"
  md: "14px"
  lg: "18px"
  card-inset: "20px 16px"
  page-inset: "34px 26px"
  page-inset-compact: "34px 16px"
  rail: "36px"
  content-max: "1180px"
components:
  button-primary:
    backgroundColor: "{colors.chambers-navy}"
    textColor: "{colors.card-white}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "10px 20px"
  button-primary-hover:
    backgroundColor: "{colors.chambers-navy-hover}"
  button-primary-pressed:
    backgroundColor: "{colors.chambers-navy-pressed}"
    padding: "11px 20px 9px"
  button-primary-disabled:
    backgroundColor: "{colors.disabled-steel}"
    textColor: "{colors.card-white}"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.slate}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "9px 16px"
  button-secondary-hover:
    backgroundColor: "{colors.navy-mist}"
    textColor: "{colors.chambers-navy}"
  button-secondary-pressed:
    backgroundColor: "{colors.navy-tint}"
    textColor: "{colors.chambers-navy}"
    padding: "10px 16px 8px"
  card:
    backgroundColor: "{colors.card-white}"
    rounded: "{rounded.card}"
    padding: "{spacing.card-inset}"
  card-secondment:
    backgroundColor: "{colors.secondment-blush}"
    rounded: "{rounded.card}"
    padding: "{spacing.card-inset}"
  card-reserved:
    backgroundColor: "{colors.info-blue-bg}"
    rounded: "{rounded.card}"
    padding: "{spacing.card-inset}"
  badge:
    typography: "{typography.caption}"
    rounded: "{rounded.pill}"
    padding: "4px 14px"
  mini-pill:
    typography: "{typography.caption}"
    rounded: "{rounded.mini-pill}"
    padding: "2px 10px"
  filter-chip:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.slate}"
    typography: "{typography.label}"
    rounded: "{rounded.chip}"
    padding: "6px 16px"
  filter-chip-checked:
    backgroundColor: "{colors.chambers-navy}"
    textColor: "{colors.card-white}"
  input:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "9px 12px"
  sidebar:
    backgroundColor: "{colors.chambers-navy}"
    textColor: "{colors.sidebar-text-muted}"
    width: "240px"
    padding: "24px 14px 18px"
  nav-item:
    textColor: "{colors.sidebar-text-muted}"
    typography: "{typography.nav}"
    rounded: "{rounded.control}"
    height: "44px"
    padding: "0 12px 0 0"
  nav-item-active:
    backgroundColor: "rgba(255,255,255,0.08)"
    textColor: "{colors.card-white}"
  time-block:
    backgroundColor: "{colors.navy-mist}"
    textColor: "{colors.chambers-navy}"
    rounded: "{rounded.block}"
    width: "78px"
    padding: "10px 6px"
  day-tile:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.chambers-navy}"
    rounded: "{rounded.block}"
    height: "74px"
    padding: "8px 12px"
  day-tile-today:
    backgroundColor: "{colors.chambers-navy}"
    textColor: "{colors.card-white}"
  kpi-card:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.ink}"
    typography: "{typography.display}"
    rounded: "{rounded.card}"
    padding: "16px 18px"
  fact-box:
    backgroundColor: "{colors.ledger-paper}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
  desk-menu:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.block}"
    padding: "6px"
  desk-menu-item-hover:
    backgroundColor: "{colors.seal-emerald-bg}"
    textColor: "{colors.seal-emerald-text}"
    rounded: "{rounded.menu-item}"
    padding: "9px 14px"
  meridiem-toggle:
    backgroundColor: "{colors.seal-emerald}"
    textColor: "{colors.card-white}"
    rounded: "9px"
    size: "40px 38px"
---

# Design System: نظام الخبراء — ExpertApp

## Overview

**Creative North Star: "The Expert's Desk" («مكتب الخبير»)**

The app should feel like a well-kept expert's desk. It sits on warm off-white paper rather than clinical white. The ink is a deep institutional navy. Emerald appears only as a seal on things that are done, connected or confirmed. Each case is its own card, and the next action on it is obvious. Calm comes from order, not emptiness. A busy week of sessions should read in one pass: time on one side, the case name in the middle, and the main action at the edge.

The interface is right-to-left Arabic throughout. The navy sidebar sits on the right as the desk's fixed spine, and pages stack beside it. Spacing is roomy enough to scan, never cramped. Controls should feel **confident and tactile**: buttons have clear weight and real padding, cards have a distinct edge, and nothing reads as a decorative ghost.

Each working page is one expression of the desk. The **sessions ledger** («دفتر اليومية») hangs each day's sessions from a navy timeline, with an emerald «الآن» line and a seal stamped on what is done. The **filing cabinet** («خزانة الملفات», pending cases) puts reserved cases first, measured by a 21-tick deadline ruler. The **inbox** («صندوق الوارد», referred cases) presents each referral as an incoming memo with labelled fact boxes. The desk tells the truth: when data is missing it says so («—», «انقطع الاتصال») instead of showing a reassuring zero.

The system rejects two things outright. The first is the **old government-system look**: dense grey grids, plain Windows buttons, Oracle Forms. The second is **loud colour**: gradients, neon, and decoration with no job to do.

**Key Characteristics:**
- Warm paper background with white cards. Depth comes from a hairline border and one very soft shadow.
- Navy is the single voice of authority. Emerald, amber and crimson only report status.
- Right-to-left everywhere, with explicit alignment helpers and isolated left-to-right text runs.
- Each card has one primary action. Everything else is secondary or tucked away.
- Line icons are drawn in code (`qt_icons.py`), never emoji.
- Motion is quiet and explanatory (120–320ms), and it respects the Windows "show animations" setting.

## Colors

A restrained palette: neutral warm paper and slate ink, one navy accent for authority, and a strict three-colour status system. Every value lives in `qt_theme.py` as a named token, and no screen file hard-codes a colour.

### Primary
- **Chambers Navy** (`chambers-navy`): the fill for every primary button, the sidebar background, the tooltip background, today's week-strip tile, the active radio indicator, the input focus border and the time-block numerals. Hover lightens to `chambers-navy-hover`, and press darkens to `chambers-navy-pressed`.
- **Navy Mist** (`navy-mist`): a barely tinted surface behind the session card's time block and the secondary-button hover.
- **Navy Tint** (`navy-tint`): quiet navy pills (session type, «غدًا», section counts) and the secondary-button press.
- **Rail Line** (`rail-line`): the 2px timeline in the sessions ledger.

### Secondary
- **Seal Emerald** (`seal-emerald`): the gliding sidebar seal, the connected status dot, the «الآن» line, the «تم» seal stamp, healthy deadline ticks (more than 7 days) and the AM/PM toggle. Its tint pair (`seal-emerald-bg` / `seal-emerald-text`) carries success pills such as «محضر اليوم جاهز» and the menu hover.
- **Emerald on Navy** (`emerald-on-navy`): small emerald text on the sidebar («متصل»), at 7.0:1.

### Tertiary (status signals)
- **Deadline Amber** (`deadline-amber`, with `-bg` / `-text`): time pressure, 7 days or fewer remaining.
- **Overdue Crimson** (`overdue-crimson`, with `-bg` / `-text`): 3 days or fewer, overdue, errors, the return-to-department action and the danger border on date and time fields. On the sidebar it becomes `danger-on-navy` («انقطع الاتصال»), at 7.5:1.
- **Info Blue** (`info-blue-bg` / `info-blue-text`, border `info-border`): reserved-case cards («محجوزة») and neutral informational notes.
- **Secondment Blush** (`secondment-blush`) with **Secondment Red** (`secondment-red`): the card background, pill and KPI colour for استعانة cases.

### Neutral
- **Ledger Paper** (`ledger-paper`): the window and page background, plus fact boxes and past-session cards. It is warm, never pure white.
- **Card White** (`card-white`): card, input, chip and menu surfaces.
- **Paper Edge** (`paper-edge`) and **Soft Edge** (`paper-edge-soft`): 1px card and field borders, the scrollbar handle and hairline separators.
- **Ink** (`ink`): primary text. **Slate** (`slate`): secondary text, subtitles, secondary buttons and «—» placeholders. **Muted** (`muted`): disabled states and decorative icons only (2.45:1, which is not readable text).
- **Ruler Track** (`ruler-track`): the empty ticks of the deadline ruler, at 3.35:1 or more on every card background.
- **Sidebar Muted** (`sidebar-text-muted`): inactive navigation labels, group captions and meta text on navy.
- **Disabled Steel** (`disabled-steel`): disabled primary buttons.
- **Login** (`login-field`, `login-field-border`, `emerald-disabled`, `emerald-disabled-text`): the dark login screen only.

### Named Rules
**The Ink-on-Paper Rule.** Chambers Navy is the only fill for a primary action. Never promote emerald, amber or any new hue to a main button.

**The Three Signals Rule.** Emerald, amber and crimson are status, not decoration. They follow the deadline thresholds: more than 7 days is emerald, 7 days or fewer is amber, 3 days or fewer or overdue is crimson. If a colour says nothing about state, it must be a neutral.

**The Dark Tone for Text Rule.** Small status text uses the dark tone of its signal (`seal-emerald-text`, `deadline-amber-text`, `overdue-crimson-text`). The bright tone is for shapes only: ticks, dots, rings. On navy, use the `*-on-navy` tones.

**The Blush Means Secondment Rule.** The blush card colour is reserved for استعانة cases. No other surface may use it, so experts can spot secondments without reading.

**The Honest Figures Rule.** When data is missing (offline, error, not logged in), figures show a neutral «—» and status says what happened. A missing value is never shown as 0, and stale data is never shown next to a failure.

## Typography

**Display Font:** Tajawal (with Segoe UI)
**Body Font:** Tajawal (with Segoe UI)

**Character:** A single Arabic sans family at every level, so hierarchy comes from size and weight rather than font contrast. It is plain, legible and administrative in the best sense. Tajawal ships inside the app (`fonts/`, four weights: Regular 400, Medium 500, Bold 700, ExtraBold 800, plus `OFL.txt`). `th.load_fonts()` registers it from `sys._MEIPASS` in the EXE or next to `qt_theme.py` in Python, from the login screen onward, and sets it as the application default font. A machine without Tajawal installed still renders it. If the folder is missing, the app falls back to Segoe UI.

### Hierarchy
- **Hero** (800, 28px): the day numeral in the sessions ledger.
- **Display** (700, 22px): KPI values and week-strip day numbers (18px in compact mode).
- **Headline** (700, 20px): the page title, with a 12–13px slate subtitle or greeting under it.
- **Title** (500, 15px): case names on cards and empty/error state titles (700 when the state offers an action). Time-block numerals use 700.
- **Nav** (500, 14px; 700 when active): sidebar navigation labels.
- **Body** (400, 13px): body text, field text and fact-box values. Primary button labels use 13px/700.
- **Label** (400–500, 12px): case numbers, KPI captions, meta lines (400); secondary buttons, chips and day names (500).
- **Caption** (500–700, 11px): pills, deadline captions and urgent signals (700); group captions and quiet meta (500). 10px only for the AM/PM marker inside the time block.

The scale is exposed as constants in `qt_theme.py`: `FS_HERO / FS_DISPLAY / FS_HEADLINE / FS_TITLE / FS_BODY / FS_LABEL / FS_CAPTION` and `W_REGULAR / W_MEDIUM / W_BOLD / W_HEAVY`.

### Named Rules
**The Four Real Weights Rule.** Use only the weights Tajawal ships: 400, 500, 700, 800. Never 600: Tajawal has no SemiBold, so Qt renders it as 700 and the hierarchy collapses. 800 is reserved for the ledger's day numeral and the seal's «تم». Hierarchy never depends on a font change.

**The Arabic Count Rule.** Counts are written as Arabic speaks them: يوم واحد / يومان / 3–10 أيام / 11+ يومًا, جلسة واحدة / جلستان / جلسات. Never «2 يوم».

## Layout

The window is a horizontal split. A fixed **240px navy sidebar** sits on the right edge (right-to-left), and a page stack takes the rest. The window opens at up to 1280×800, about 92% × 88% of the available screen, centred, with a hard minimum of 1080×660. Pages are laid out in one column and do not reflow into multiple columns.

**Adaptive column:** page content is capped at **1180px** and centred. On wide screens (1920, 2560, 4K) the side margins grow and the cards keep a readable width, so the primary action never drifts far from the case name. Below **760px** of height the page switches to **compact mode**: tighter page and KPI padding, 64px week tiles with an 18px numeral, and 12px section spacing. No content is removed. Icons are drawn at the screen's real device-pixel ratio, so they stay sharp at 250–300% scaling.

Spacing follows a small set of steps: 4 / 6 / 10 / 14 / 18px between items, with 10 the most common. Page content is inset 34×26px (34×16 compact). Cards are padded 20×16px. Inside a session card, information flows in three blocks: time on the right, details in the middle, actions on the left. The sessions ledger reserves a **36px rail** on the reading edge for the timeline.

### Named Rules
**The Absolute Right Rule.** Never use bare `AlignRight`/`AlignLeft`. Inside a right-to-left app Qt flips them. Always use `th.ARIGHT` / `th.ALEFT`, which include `AlignAbsolute`, and wrap any left-to-right text inside Arabic (file paths, Latin case numbers like A2261085, dates, URLs) in `th.ltr()` so it is not reversed.

**The Readable Column Rule.** Never let a list stretch past 1180px. Grow the margins, not the cards.

## Elevation & Depth

A hybrid of tonal layers and one soft shadow. The main depth step is tonal: the solid navy sidebar against warm paper. Cards then lift slightly off the paper with a 1px Paper Edge border and a single, very diffuse drop shadow tinted with ink rather than black. Past sessions drop their shadow and melt into the paper. Nothing else casts a shadow, and shadows never change on hover.

### Shadow Vocabulary
- **Desk Shadow** (`QGraphicsDropShadowEffect`: blur 22, offset 0/6, `rgba(15,23,42,0.07)`; CSS equivalent `0 6px 22px rgba(15,23,42,0.07)`): every `Card`, applied by `soft_shadow()`. During a fade-in it is swapped for an opacity effect and restored afterwards, because Qt allows one effect per widget.

### Named Rules
**The One Shadow Rule.** There is one shadow and only cards get it. If something needs more emphasis, give it colour or weight, never a heavier shadow.

## Shapes

Soft, generous corners that grow with the size of the surface: **16px** for cards, **12px** for inset blocks (time block, day tiles, menus), **10px** for buttons, fields, nav items and fact boxes, **8px** for menu items, **6px** for tooltips, **3px** for bars, **20px pills** for badges, **15px** for filter chips and **9px** for the small inline pills that sit beside a case number. Borders are always 1px hairlines in Paper Edge. The sharp accents are thin and deliberate: the **3px emerald seal** in the sidebar, the **2px navy rail**, the **2px emerald «الآن» line** and the **2.2px ticks** of the deadline ruler.

## Components

### Buttons
Confident, solid and clearly clickable, with a pointer cursor on every one.
- **Shape:** gently rounded (10px).
- **Primary:** Chambers Navy fill, white 13px/700 label, 10×20px padding. The main action of a card or dialog ("طباعة المحضر", "محضر أول جلسة", "مباشرة (استلام)"). Icons are drawn in white.
- **Hover / Pressed / Disabled:** hover lightens to `chambers-navy-hover`. Press darkens to `chambers-navy-pressed` and nudges the label down 1px, which is tactile and instant with no animation. Disabled becomes Disabled Steel.
- **Secondary:** transparent with a 1px Paper Edge border, slate 12px/500 label, 9×16px padding. Hover fills with Navy Mist and turns navy. Press fills with Navy Tint and nudges down 1px.
- **Danger outline:** the secondary shape with a crimson border and label, plus the drawn return icon. Used only for «إعادة لرئيس القسم».

### Chips / Badges
- **Badge:** pill (20px), 4×14px padding, 11px/700, always a tint pair.
- **Mini pill:** 9px corners, 2×10px padding, 11px/700. It sits inline beside a case number: session type (navy tint), «محجوزة» (white with info text), «استعانة» (white with secondment red), «محضر اليوم جاهز» (emerald tint), «اليوم» (emerald tint), «غدًا» (navy tint).
- **Filter chip** (pending page): 15px corners, white with a Paper Edge border, 12px/500. Checked becomes a navy fill with white 700. It filters the loaded list in view only. Counts appear in the label, and are hidden when data is missing.
- Badges and pills only report status and are never clickable.

### Cards / Containers
- **Corner Style:** 16px.
- **Background:** Card White. Blush for استعانة, Info Blue for reserved (محجوزة), Ledger Paper for past sessions.
- **Shadow Strategy:** the Desk Shadow (see Elevation & Depth).
- **Border:** 1px Paper Edge (Info Border on reserved cards).
- **Internal Padding:** 20×16px.

### Inputs / Fields
- **Style:** white background, 1px Paper Edge border, 10px corners, 9×12px padding, 13px Ink text, right-aligned.
- **Focus:** the border turns Chambers Navy. No glow.
- **Error:** the border turns Overdue Crimson (`danger=True`).
- **Smart Date** (`SmartDateEdit`): accepts shorthand like `17`, `1706` or `17/6` and completes it when focus leaves.
- **Smart Time** (`SmartTimeEdit`): a 90px time field next to a 40×38px emerald **ص/م toggle**, limited to working hours (up to 15:00).

### Navigation (sidebar)
- **Spine:** solid Chambers Navy, 240px wide, 24/14/18px inset. At the top: a 36px logo, a 15px/700 white app name and a status row (8px painted dot plus 11px label).
- **Status:** three honest states. **متصل** (emerald dot, `emerald-on-navy` label), **انقطع الاتصال** (`danger-on-navy`) and **غير متصل** (sidebar muted). It is fed by the sessions page's `connection_state` signal through the page stack.
- **Groups:** «عملي» (sessions, pending, referred) and «رئيس القسم» (add case, case lookup; shown only to authorised users), each under an 11px/700 caption. Settings is pinned to the bottom.
- **Items:** 44px tall, 10px corners, an 18px drawn line icon and a 14px label. Hover gets a 0.04 white wash and white text. Active gets a 0.08 wash with a white 700 label.
- **The seal:** a single 3×22px emerald bar that **glides** between items (240ms) instead of each item owning a marker.
- **Footer:** a hairline separator, a 34px initials avatar, the user name in 13px/700 white and «تسجيل الخروج» in sidebar muted. That label is currently inert.
- **Shortcuts:** Ctrl+1/2/3 for the three working pages, and F5 refreshes the visible page through its own refresh handler.

### Desk Menu («إجراءات أخرى»)
A white sheet with 12px corners and 6px padding, opened directly under its button and aligned to its right edge. Items are 13px with 9×14px padding and 8px corners, each with an 18px drawn icon (calendar, government building, clock-plus). Hover gives an emerald tint with dark emerald text and icon. A hairline separator isolates actions that **write to the expert system** from actions that stay on the expert's machine.

### Sessions Ledger (signature component)
- **Week strip:** five tiles for the Kuwaiti work week (Sunday–Thursday; on Friday and Saturday it shows next week). Each tile has a 12px/500 day name, a 22px/700 numeral and up to six count dots. Today is a navy fill with emerald dots. Clicking a tile glides the list to that day (280ms). When data is missing the tiles turn neutral rather than looking empty.
- **Rail and day chapters:** a 36px gutter with a 2px Rail Line. Each day has a 28px/800 numeral, the day name and date, and an «اليوم» or «غدًا» pill. Nodes: solid navy for future days, an emerald ring for today, small rings for sessions (muted once past).
- **Session card:** time block (78px, Navy Mist, 15px/700), case name (15px/500, elided to the real width with a full-name tooltip), meta line (case number, mini pills), then «إجراءات أخرى» and «طباعة المحضر».
- **«الآن» line:** a 2px emerald line with an 11px/700 label, placed among today's sessions by time and re-placed every minute. Once all of today's sessions have passed it reads «انتهت جلسات اليوم». At midnight the strip and chapters rebuild from the loaded data.
- **The seal stamp («تم»):** after a محضر file appears in `Desktop\محاضر\<case>` (a read-only check), a 68px emerald double ring with «تم» at −10° presses onto the card: it scales from 115% to 100% while fading in, over 320ms, once. It never appears unless the file really exists.
- **Greeting:** the header subtitle reads the loaded day: «صباح الخير — لديك 3 جلسات اليوم، أقربها 11:30 صباحاً», «انتهت جلسات اليوم», «لا جلسات اليوم، أقربها …», or «عطلة نهاية الأسبوع — أقرب جلسة …». It is hidden when figures are unknown.
- **No-upcoming drawer:** collapsed by default, with a crimson count pill. It opens with a 220ms height animation and quiet secondary «إضافة جلسة قادمة» rows.

### Deadline Ruler (signature component, pending page)
- **Ticks:** 21 ticks, one per day of the report window, at a 6px pitch: 2.2px wide, 7px tall, and 11px for each week's end. Elapsed days fill from the reading edge in the signal's bright tone. Remaining days are Ruler Track.
- **Caption:** 11px/700 in the signal's dark tone, stating the due date, for example «متبقي يومان · حتى الثلاثاء 06/10», «الموعد اليوم · …» or «تجاوز الموعد بيومين · كان الجمعة 02/10».
- **Tooltip:** explains the ruler («كل علامة يوم من مهلة الـ21 يومًا، والعلامة الطويلة نهاية أسبوع»).
- **Placement:** reserved cases are listed first, sorted by the nearest deadline.

### Incoming Memo (signature component, referred page)
Plaintiff as the title, then «رقم الخبرة · ورد في …», then labelled **fact boxes** (من قسم / من موظف / ملاحظات; Ledger Paper, Soft Edge, 10px corners, 11px/500 caption over a 13px value; notes take double width), then «مباشرة (استلام)» (primary, check icon) and «إعادة لرئيس القسم» (danger outline, return icon). Direct referrals and secondments are listed in separate counted sections.

### States (empty / loading / offline / error)
These are shown inline in the list, never as a popup. Each has a 36px drawn icon, a 15px title and a 12px slate line.
- **Offline:** «لا يوجد اتصال بنظام الخبراء» with a primary «إعادة المحاولة» that calls the page's existing loader.
- **Not logged in:** the same title with «سجّل الدخول من جديد…» and **no button**, because nothing on the page can log in.
- **Error:** «تعذّر تحميل …» with «حدث خطأ غير متوقع أثناء قراءة البيانات». The technical text is hidden behind «عرض التفاصيل» and is selectable.
- **Empty:** a domain icon with the domain sentence («لا توجد جلسات قادمة» / «تظهر هنا جلسات الثلاثين يومًا القادمة»).

### KPI Card
A card with 18×16px padding (18×10 compact): a 12px slate caption above a 22px/700 value. The value is Ink by default, a status colour only when the number itself is a signal (amber only when «بدون جلسة قادمة» is above 0), and a slate «—» when unknown.

### Motion
The motion lives in `qt_motion.py`. It explains state and never decorates.
- **Durations:** 120–150ms for feedback, 180–280ms for routine changes, 320ms for the one authored moment (the seal). Curve: OutCubic (decelerating). No bounce, no loops.
- **Seal glide** (sidebar, 240ms), **page fade** (180ms), **card cascade** (200ms each, 25ms apart, at most 8 cards; 140ms/18ms when a filter changes), **drawer** (220ms height plus row fade), **list glide** to a day (280ms).
- **Reduced motion:** when Windows "show animations" is off, spatial motion (glide, cascade) is removed and only a ≤90ms fade remains to mark the change.
- After a fade, the widget's original effect (the Desk Shadow) is restored and no opacity effect is left running.

## Do's and Don'ts

### Do:
- **Do** take every colour, corner size and button style from `qt_theme.py` (`th.NAVY`, `th.RADIUS_CARD`, `th.primary_button_style()`), every shared widget from `qt_widgets.py`, every icon from `qt_icons.py` and every animation from `qt_motion.py`.
- **Do** give each card exactly one `PrimaryButton`. Additional actions go in a `SecondaryButton` or the «إجراءات أخرى» desk menu.
- **Do** align with `th.ARIGHT` / `th.ALEFT` and wrap left-to-right text (paths, Latin case numbers, dates) in `th.ltr()`.
- **Do** use the Three Signals Rule for every deadline or status, with the dark tone for small text.
- **Do** show «—» and an honest status when data is missing (the Honest Figures Rule).
- **Do** cap content at 1180px and let compact mode handle short screens.
- **Do** keep controls confident: buttons at least 38px tall with real padding, a pressed state, and a pointer cursor on every clickable element.

### Don't:
- **Don't** recreate the old government-system look: dense grey grids, plain Windows buttons, Oracle Forms-style crowding.
- **Don't** use loud colour: no gradients, no neon, no purely decorative accents.
- **Don't** use any fill other than Chambers Navy for a primary action.
- **Don't** add new shadows or deepen the Desk Shadow. Emphasis comes from colour and weight.
- **Don't** use font weight 600, and don't write «2 يوم».
- **Don't** use `muted` (#94A3B8) for readable text. Known open gap: it is still used for some past-session times, empty-tile numerals and small notes.
- **Don't** use emoji as icons. Known open gap: ⚠️ ✅ ❌ remain inside the referred-page confirmation dialogs, which are business logic preserved verbatim.
- **Don't** rely on hover alone for meaning. Known open gap: keyboard focus rings are not implemented yet, and needs a focus-policy line in `qt_widgets.py`.
