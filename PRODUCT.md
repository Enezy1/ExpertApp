# Product

<!-- impeccable:product-schema 1 -->

## Platform

desktop

Windows desktop app built with Python and PyQt6, shipped as a PyInstaller EXE with an Inno Setup installer. It is not a web, iOS or Android product. Web-only tooling (live mode, generate, the HTML detector) does not apply.

## Users

- **Primary:** the experts in the owner's department at the General Administration of Experts (الإدارة العامة للخبراء), Ministry of Justice, Kuwait. This is a small group the owner knows personally. They use the app daily in the office to manage their sessions, records (محاضر) and cases.
- **Head of department (رئيس القسم):** uses the extra tools: adding new cases, case lookup, department session reports and statistics. Access is granted by name through Supabase, and the owner is always authorized.
- **Later:** the app may expand to other departments in the administration. This is not a current commitment.

## Product Purpose

An automation layer over the ministry's expert system (`expertapp.moj.gov.kw`) and the automated case file system. It brings together work that is otherwise spread across several government systems, Word templates and manual entry. The guiding idea is "one button" (الزر الواحد).

Success means:

1. **A clear picture of every case.** The expert knows where each case stands (متداولة / محجوزة / محالة / منجزة / مستبعدة), and the statistics are accurate.
2. **Time saved.** A record (محضر), first-session record or government notice is ready with one action instead of being written by hand and re-entered across systems.
3. **Oversight for the head of department.** This covers department reports, adding cases and following the experts' workload.

## Positioning

It is built from inside the department by a working expert and department head. It encodes real procedural rules that general tools cannot: the case flow log (ECS_CASE_FLOW) and its classification rules, session type codes, the Kuwaiti work week (Sunday to Thursday), the court-session fallback logic and the official document templates. It reads the referral judgment with AI and schedules the next session automatically.

## Operating Context

- Used in the ministry office, on the work network. Some data sources (Access DB `ExpretDB.mdb`, the documents server at 10.100.105.6) are only reachable there.
- Login uses browser cookies or OTP through WebView. Each expert has their own settings folder in `%LOCALAPPDATA%\ExpertApp\experts\{name}\`.
- Outputs are official Word documents (`ma7dar_template.dotx`, `اخطار_حكومه.dotx`), HTML weekly and department reports, and iCloud calendar events.
- Main screens: sessions, pending/booked cases, referred cases, case lookup, add case and department reports (head of department), and settings.

## Capabilities and Constraints

- **The whole interface is right-to-left Arabic** (text, alignment and element order). This is a fixed rule.
- Write endpoints on the expert system are limited. Only `insert.php` works, so session types cannot be edited or deleted from the app.
- A case is not saved locally without a Gemini key. Authorization is by expert name, never by account number.
- The PyQt6 UI is current. CustomTkinter modules remain as the logic layer that the Qt screens import.
- Terminology to keep as-is: محضر، أول جلسة، إخطار حكومي، متداولة، محجوزة، محالة، مباشرة، استعانة، أصالة، إعادة توزيع، حجز للتقرير، كشف أسبوعي.
- The meaning of session colour `#0e5480` is still unknown (open question).

## Brand Commitments

- **Personal initiative, not an official ministry product.** Do not present it as an approved MOJ system.
- The logo of the General Administration of Experts (`الاداره العامه للخبراء.jpg`) may be used as identity.
- The app name in use is «نظام الخبراء» / ExpertApp, with the existing `app_icon.png` / `app_icon.ico`.

## Evidence on Hand

- Real department workflows and real case examples used in testing (e.g. A2261085, A2261284), documented in `PROJECT_MEMORY.md`.
- The official Word templates and the department logo are in the project root.
- There are no user testimonials, usage metrics or adoption numbers. Do not invent them.

## Product Principles

1. **Correctness over convenience.** A wrong case status or session is worse than a missing feature. Show the source of truth and ask for explicit confirmation before writing to government systems.
2. **One action for routine work.** Common tasks (a record, a notice, the next session) should take a single deliberate step.
3. **Status at a glance.** An expert should know their workload and what needs attention without hunting through screens.
4. **Native to the work.** Use the department's own Arabic terms, documents and calendar (Sunday to Thursday), not generic task-manager language.
5. **Quiet authority.** It is a personal initiative serving official work, so it should feel trustworthy and calm without claiming to be official.

## Accessibility & Inclusion

Full RTL Arabic support is required everywhere, including dialogs, reports and generated documents. Bidirectional text such as dates and case numbers inside Arabic must render correctly.
