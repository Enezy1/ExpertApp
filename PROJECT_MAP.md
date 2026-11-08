# 🗺️ PROJECT_MAP — خريطة مشروع ExpertApp (نظام الخبراء)

> **🤖 خريطة استدعاءات Gemini (وظيفة ← دالة ← مهمة ← موديل ← حصة):** انظر `كيف_يعمل_التقرير.md` القسم 9 — `ai_providers.MODEL_ROUTES` + `gemini_quota.py` + `summary_queue.py` (23 أكتوبر 2026).
> **🆓 الخطة المجانية (25 أكتوبر 2026):** `كيف_يعمل_التقرير.md` §9–10 — `gemini_config.rank` (أسماء فعلية) + `FALLBACK_ROUTES` + `attempt_budget` (محاولتان) + `doc_header.py` (رأس نوع المستند) + `case_sort.retriage` (فرز مجمّع) + `case_sources.store_claim`/`dedupe_claims` + `report_v3.rewrite_axis` + `report_audit.dedupe` + `cloud_files.py` + `telecom_reports.fetch_all`/`filter_cases` + `app_paths.py` (`EXPERTAPP_LOG_DIR`).

> **الغرض:** مرجع سريع لكل ملف ووظيفته ودواله المهمة، حتى لا نحتاج فتح كل الملفات في كل جلسة.
> **الفرق عن `PROJECT_MEMORY.md`:** هذا الملف = **خريطة الكود الثابتة** (وين كل شي). الآخر = **حالة المشروع المتحرّكة** (وين وصلنا).
> **🕒 آخر تحديث:** 21 أكتوبر 2026 (البنية المختصرة لمجلد القضية + خط البداية + الفرز + العقد + الملخص + الكتابة التلقائية + منع الحلقة — آخر الملف؛ قبله مفاتيح الخبير الشخصية + DPAPI؛ قبله التقرير المركَّب بالكود v3: case_facts + calc.ledger + report_playbooks + report_compose + report_audit + report_v3 + أقوى Gemini Pro + إصلاح زر 🔄 OCR — انظر آخر الملف)

---

## نظرة عامة على البنية (الواجهة الحالية = PyQt6)

```
تشغيل → main.py (شاشة دخول Qt + كوكيز Firefox/Edge/Chrome + تسجيل الخبير أونلاين)
          ↓
       qt_shell_v2.py (النافذة الرئيسية: Sidebar + QStackedWidget)
          ├── qt_sessions_page.py   → الجلسات + محضر عادي + إخطار حكومي + كشف أسبوعي
          ├── qt_pending_page_v2.py → المتداولة/المحجوزة → qt_first_session.py (محضر أول جلسة)
          ├── qt_referred_page_v2.py → المحالة (مباشرة/إعادة)
          ├── qt_case_lookup.py     → بحث قضية (رئيس القسم)
          ├── qt_main1.py           → إضافة قضية جديدة + كشوفات القسم (رئيس القسم)
          └── qt_settings_page.py   → الإعدادات (+ إدارة صلاحيات رئيس القسم)

الواجهة القديمة (CustomTkinter — لا تزال المصدر المنطقي، تستوردها شاشات Qt):
  ui.py / pending_cases.py / referred_cases.py / settings_page.py /
  case_info_window.py / first_session.py

مصادر البيانات:
  api.py          ← نظام الخبراء (expertapp.moj.gov.kw)
  documents.py    ← نظام الملف الآلي (حكم الإحالة PDF، IP 10.100.105.6)
  case_info_window ← استخراج شامل من الحكم (ai_reader.py القديم نُقل إلى `قديم/cleanup-2026-10-17/`)
  case_db.py      ← تخزين محلي (SQLite) لكل قضية
  case_stats.py   ← محرك الإحصائية (تحليل ECS_CASE_FLOW)
  db_writer.py    ← الكتابة على قاعدة Access (ExpretDB.MDB) — رئيس القسم

إعدادات لكل خبير (current_expert.py يحدد المجلد):
  gemini_config.py / expert_settings.py / icloud_calendar.py

السحابة (Supabase):
  cloud_sync.py / main1_config.py
  main1_access.py         ← صلاحية "إضافة قضية جديدة" (بالاسم)
  experts_registry.py     ← سجل أسماء الخبراء الموحّد أونلاين
  qt_main1_access_dialog.py ← نافذة إدارة الصلاحيات (المالك)

التصميم (Design System): qt_theme.py / qt_widgets.py
```

---

## الملفات الأساسية

### main.py — نقطة التشغيل
شاشة تسجيل الدخول (LoginScreenQt)، تثبيت المكتبات تلقائيًا (عند python فقط لا EXE)،
حفظ/قراءة الحسابات من `%LOCALAPPDATA%\ExpertApp\credentials.json` (متعددة على نفس الجهاز).
`try_get_cookies` (Firefox سريع) / `login_with_webview` (OTP). عند نجاح الدخول (`_open_app`):
- `current_expert.set_current_user(user)` + `set_current_account(username)`.
- 🆕 `experts_registry.register_expert(user, account_no)` — تسجيل الاسم أونلاين (best-effort صامت).
- `cloud_sync.try_sync_on_startup(user)` ثم يفتح `qt_shell.ExpertAppQt`.

### config.py — الثوابت
- `BASE_URL` · `TEMPLATE_PATH`/`GOV_TEMPLATE_PATH` (يدعم `_MEIPASS`) · `SUPABASE_URL`/`SUPABASE_KEY`.
- `SESSION_TYPES` (أكواد) · `SESSION_COLORS` (#27659a=فتح محضر، #0d95b8=مناقشة، #132294=حجز للتقرير).
- `IGNORED_SESSION_COLORS={#27659a}` · `DAYS_AR` · `GOVERNORATES` · `GOV_KEYWORDS`.
- ⚠️ اللون `#0e5480` لسه غير معروف.

### current_expert.py — تحديد الخبير الحالي
- `set_current_user`/`get_current_user` · `set_current_account`/`get_current_account` (رقم الحساب، معلومة إضافية فقط — غير موثوق للتخويل).
- `expert_data_dir()` → `%LOCALAPPDATA%\ExpertApp\experts\{name}\`.
- ملاحظة: `case_db` تبقى **مشتركة** عمدًا.

### dates.py — تطبيع التواريخ
- `normalize_date()` → دائمًا DD/MM/YYYY (يتعرف على موضع السنة). كل تاريخ يمر عليها أولًا.

---

## طبقة البيانات / السيرفر

### api.py — التواصل مع نظام الخبراء
| دالة | وظيفة |
|---|---|
| `get_logged_in_name(cookies)` | **اسم المستخدم من الهيدر (الاسم المعروض الموثوق — مصدر التخويل والتسجيل).** |
| `get_sessions` / `get_all_case_sessions` | جلسات نطاق تاريخ / كل جلسات قضية |
| `parse_case_info` | بيانات القضية الكاملة |
| `get_requesting_expert` / `get_original_experts` | الخبير المستعين / الأصليون (استعانة) |
| `insert_session(...)` | إضافة جلسة عبر includes/insert.php. النتيجة: 1=نجح 2=خطأ 3=تعارض 4=حجز 5=إجازة 6=<7أيام |
| `get_case_parties_summary` / `session_exists` / `compute_session_number` | مساعدات |

#### ⚠️ endpoints الكتابة (includes/)
- **insert.php** ✅ الوحيد الموثوق. **update.php** ❌ نجاح وهمي (`{id}hiiii`) بلا كتابة. **delete.php** ❌ PDOException.
- **الخلاصة:** تعديل/حذف نوع الجلسة غير ممكن (البديل: Oracle Forms يدويًا). مسار السيرفر: `C:\Apache24\htdocs\includes\`.

#### أكواد أنواع الجلسات (EMET_TYPE)
مناقشة=150003، معاينة=150001، اطلاع وانتقال=150002، فتح محضر=150004، حجز للتقرير=150005، حجز للصلح=150006، حجز للإعادة=150007، للإعلان=150008، إجراءات إدارية=150010، جلسة محكمة=150011.

#### مصادر set_sourc.php (لوحة METMONTH)
`motadawal`=المتداولة، `BookedNoEdecision`=المحجوزة، `mubashara`=المباشرة.

### documents.py — حكم الإحالة (الملف الآلي)
IP ثابت `10.100.105.6`. ترتيب البحث: تمييز → استئناف → كلية.
`build_doc_link`/`get_documents_page`/`parse_sections`/`find_most_recent_judgment`/`download_judgment_pdf`/`get_referral_judgment_for_case`/`get_case_documents_bundle` (حكم+صحيفة+تقرير).

### ai_reader.py — ⚠️ منقول إلى `قديم/cleanup-2026-10-17/` (لا يستورده أحد) — استخراج تواريخ الحكم (Qwen)
`read_judgment_dates_from_pdf` عبر Playwright → {judgment_date, hearing_date, success}.

### case_db.py — قاعدة SQLite محلية
`%LOCALAPPDATA%\ExpertApp\cases.db`. جداول: `cases` + `sessions` + `case_flow_stats`.
`init_db`/`has_case`/`get_case`/`save_case`/`update_status`/`upsert_session`/`get_no_upcoming_cases`/`save_case_stats`.
⚠️ لا تُحفظ قضية بدون أي مزود AI متاح (`ai_providers.has_any_provider`). الإحصائيات منفصلة لكل خبير (caso_no+expert_name).

### case_stats.py — محرك الإحصائية
تحليل `ECS_CASE_FLOW`: `_build_dist_clusters` (كتل اللجان)، `get_case_snapshot`، `analyze_case_flow`،
`run_full_scan`، `build_report_data`/`build_full_stats_report_html`. يدعم الأصالة والاستعانة.

### db_writer.py — الكتابة على Access (رئيس القسم)
الجدول الصحيح اسمه **`main`** (أسماء إنجليزية بـ SQL). `insert_case_record`،
`parse_expertise_number`/`parse_court_case_number`، `get_expert_names` (أسماء من جدول `[اسم الخبير]` — **احتياط** الآن بعد التحويل لسجل أونلاين)، `get_department_week_sessions`.

---

## توليد المستندات
- **mahdar.py** — محضر عادي (معالجة XML: `fix_dotx`/`make_run`/`replace_cell`/`append_after_text`/`fill_mahdar`). ⚠️ حقول التاريخ بالفقرات لا تُعكس؛ خلايا الهيدر تُعكس (bidi).
- **gov_notice.py** — إخطار الجهة الحكومية (`fill_gov_notice`، كشف الأطراف الحكومية + `inject_recipient`).
- **first_session.py** — محضر أول جلسة (أصالة/استعانة). `get_upcoming_session`/`find_open_record_session` (يعتمدان `received_date` كخط فاصل)، `insert_session_no_conflict` (+دقيقة حتى 60)، `_ensure_next_session`.
- **weekly_report.py** — كشف أسبوعي HTML (أسبوع الكويت أحد→خميس).
- **department_report.py** — كشف جلسات القسم (من Access، صفحة لكل خبير).

**منطق `_ensure_next_session`:** استعانة → نافذة+مناقشة | أصالة قبل الموعد → محكمة 12:00 صامت | أصالة متأخرة → نافذة+مناقشة | حارس تكرار لو الجلسة موجودة.

---

## الواجهة PyQt6 (الحالية)
- **qt_shell_v2.py** — النافذة الرئيسية + Sidebar + `load_app_icon` (تستوردها qt_login_ui). (qt_shell.py القديم منقول إلى `قديم/cleanup-2026-10-17/`.) تُخفي أدوات رئيس القسم عن غير المخوّلين (`_is_authorized_for_main1` → `main1_access`).
- **qt_sessions_page.py** — `SessionCardQt` + `AddSessionDialog` + `WeeklyReportDialog` + طباعة محضر/إخطار.
- **qt_pending_page_v2.py** (القديمة qt_pending_page.py منقولة) — `PendingCaseCard` + `ReferredStatsDialog` + `DeadlineIndicator` + محضر أول جلسة.
- **qt_referred_page_v2.py** (القديمة qt_referred_page.py منقولة) — `ReferredCaseCard` (مباشرة/إعادة بتأكيد صريح).
- **qt_case_info.py / qt_first_session.py / qt_case_lookup.py** — نسخ Qt تعيد استخدام المنطق القديم.
- **qt_main1.py** — `Main1Page` (إضافة قضية) + `DepartmentReportDialog` + `is_authorized_for_main1` → `main1_access`.
- **qt_theme.py / qt_widgets.py** — الألوان + المكوّنات (Card/Badge/أزرار/SmartDateEdit/SmartTimeEdit، RTL كامل).

**الواجهة القديمة (CustomTkinter):** `ui.py` (get_experts، SessionCard، ExpertApp)، `pending_cases.py`، `referred_cases.py`، `case_info_window.py`، `settings_page.py`، `first_session.py` — يستوردها Qt للمنطق.

---

## الإعدادات الشخصية (لكل خبير)
- **gemini_config.py** — مفتاح Gemini + مفتاح OCR.space الخاص (`save/load_ocr_key`) بمجلد الخبير. ترحيل تلقائي (move). + الاتصال والإرسال (انظر القسم التالي).
- **expert_settings.py** — `save/load_specialty` + `save/load_location` (مقر/دور/مكتب/جناح).
- **icloud_calendar.py** — CalDAV (App-Specific Password). `test_connection` (كتابة فعلية)، `add_calendar_event`، dedup عبر date_search.
- ~~gemini_setup.py~~ — منقول إلى `قديم/cleanup-2026-10-17/` مع `gemini_profile/` و`copilot_profile/` (غير مستخدمة).

---

## 🆕 صلاحية "إضافة قضية جديدة" + سجل الخبراء (أونلاين)
- **experts_registry.py** — `register_expert(name, account_no)` (upsert تلقائي عند الدخول، best-effort صامت) + `list_experts()` (المصدر الموحّد للأسماء، مع كاش `experts_cache.json`). جدول Supabase `experts`.
- **main1_access.py** — التخويل **بالاسم** (لا رقم الحساب). `is_owner`/`is_authorized_for_main1`/`grant_access`/`revoke_access`/`list_authorized`. المالك مخوّل دائمًا. مطابقة بالأول+الأخير. كاش `main1_access_cache.json`. جدول `main1_authorized_users`.
- **qt_main1_access_dialog.py** — نافذة المالك (من الإعدادات): قائمة أسماء منسدلة من registry + منح/سحب.

**جداول Supabase:** `experts(expert_name PK, account_no, first_seen, last_seen)` · `main1_authorized_users(expert_name PK, granted_by, granted_at)` · (+القديمة: `app_config`, `cases`, `expert_sync_status`).
**SQL:** `supabase_setup_all.sql` (مدموج، آمن للتكرار) أو المنفصلة `supabase_experts.sql` + `supabase_main1_access.sql`.

---

## 🆕 الذكاء الاصطناعي: الاتصال والمزودات وOCR (أكتوبر 2026)
- **gemini_config.py** — `start_connection_check`/`check_connection` (بروكسي/مباشر)، `_run_with_routes` (محاولتان + الطريق الآخر)، `compute_timeout` (60+10×صفحة، حد 180)، `prepare_pdf` (قص/نص/ضغط 150DPI رمادي JPEG70 بـPyMuPDF)، **`generate_from_pdf`** (المسار الكامل)، `generate_content_with_fallback` (طلبات نصية)، `_log` → `%LOCALAPPDATA%\ExpertApp\gemini_connection.log`، `is_admin` (= `main1_access.is_owner`).
- **ai_providers.py** — `Provider` → `GeminiProvider` / `OpenAICompatProvider` (أي API متوافق مع OpenAI؛ صور مقسّمة حسب `max_images` + دمج). `build_text_chain` (احتياطي ثم Gemini) / `build_image_chain` (Gemini ثم احتياطي) / `run_chain`. أدوات الأدمن: `save_provider_config` / `list_providers_for_admin` / `test_provider` / `_test_ocr`.
- **ocr_space.py** — `ocr_pages(pdf, idx, route)`؛ صفحة/طلب < 1MB، محرك 3 ثم 2 (`auto`)، `_looks_valid` (≥20 حرف عربي و50% عربي)، عدادات `ocr_quota.json` (500/يوم، 25000/شهر، محرك3 1000/شهر، هامش 95%). مفتاح الخبير الخاص يتقدم بعداد مستقل.
- **دمج الإعدادات:** صف Supabase يتقدم على `gemini_network.ini` لنفس الاسم، **إلا المفتاح الفاضي** (يُؤخذ المحلي). `save_provider_config` بلا مفتاح يرفع المفتاح الموجود.
- **provider_sync.py** — `refresh` (Supabase → `ai_providers_cache.json`)، `start_refresh` (عند التشغيل)، `get_configs`، `upsert`، `is_shared`/`set_shared` (صف `_share`). التخزين: `app_version` صف id=2.
- **gemini_network.ini** (بجانب البرنامج/EXE) — `[network] proxy_url` · `[pdf]` إعدادات القص · `[provider:<name>]` إعدادات محلية احتياطية (Supabase يتقدم عليها).
- **qt_settings_page.py** — بطاقة «مفتاح OCR.space الخاص» (للكل) · «المزودات الاحتياطية» (أدمن: حفظ وتفعيل للقسم/اختبار/حذف/أولوية + مربع المشاركة) · «تشخيص اتصال الذكاء الاصطناعي» (أدمن، آخر بطاقة).

### 🆕 OCR داخلي على الجهاز (أكتوبر 2026) — يقلل OCR.space وصور Gemini ويعمل بلا إنترنت
- **ocr_engine.py** — محرّك PP-OCRv5 (ONNX على المعالج، داخل EXE): تقويم الميل، الرقم قطعة واحدة، استرجاع "٠" و"/".
  النموذجان في `ocr/models` (~13MB، مضمّنان بالـspec).
- **local_ocr.py** — `read_pages(pdf, idx)` → نص بصيغة `--- صفحة N ---` + لكل صفحة: weak (ضجيج ≥10% أو ثقة < 0.55)، digits (indic/latin)، table.
- **gemini_config.local_text_for** (داخل `generate_from_pdf(..., purpose)`) قبل OCR.space:
  `summary` ← النص الداخلي يكفي (حتى مع أخطاء) → نص للذكاء، بلا OCR.space ولا صور.
  `extract` ← فقط إن كانت الأرقام إنجليزية ولا جدول ولا صفحة ضعيفة؛ الأرقام الهندية → OCR.space/الذكاء كالسابق.
  سجل الاتصال: `LOCAL-OK` / `LOCAL-SKIP` / `LOCAL-FAIL`. أي فشل → المسار القديم كما هو.
- **بلا مزود/اتصال:** `summarizer._local_summary` (طلب الصحيفة "ليسمع الحكم بـ…" معلَّم «ملخص محلي»)؛
  `extract_from_pdf(allow_local=True)` → **local_extract.py** (قواعد) + `_warning` — **فقط** بشاشة إضافة قضية (qt_main1، فيها مراجعة).
  الجلب الصامت (case_info) لا يستخدمه عمدًا: تاريخ خاطئ محفوظ لا يُعاد استخراجه.
- القياس (أحكام حقيقية، 99 صفحة): الكلمات 97%، الأرقام الهندية 11/38 فقط ⇐ سبب قاعدة الأرقام. ~9 ث/صفحة.
- **spec:** `collect_dynamic_libs('onnxruntime')` لا `collect_all` (الأخير سحب torch/scipy/pandas). استبعادها `OCR_EXCLUDES`
  (استيراداتها كلها اختيارية) — EXE تجريبي 290MB بدل 391MB للنسخة السابقة.
- نسخة احتياطية للملفات قبل التعديل: `قديم\backup-ocr-20261010\`.

**إضافة مزود جديد:** متوافق مع OpenAI → أضفه بـ`_DEFAULT_PROVIDERS` (kind=openai، base_url، model، max_images) واحفظ مفتاحه من الشاشة. واجهة مختلفة → كلاس يرث `Provider` (generate + generate_text) ويُسجَّل في `PROVIDER_KINDS`.

---

## 🆕 تقارير الخبراء — المرحلة 1 (أكتوبر 2026)
- `telecom_config.py`: قسم `[telecom_companies]` في `gemini_network.ini` (أوريدو/زين/stc مثبّتة افتراضياً — `DEFAULT_COMPANIES` — ويعدّلها المستخدم يدوياً في الملف بلا واجهة)، `normalize` و`match_company(text)` (ة/ه، أ/إ/ا، ى/ي، حدود كلمة + بادئة عربية؛ **الصيغة الأطول تفوز**)، `split_plaintiff(title)` (ما قبل «ضد»). `save_companies` يستبدل القسم فقط.
- `telecom_reports.py`: `get_my_telecom_cases(cookies, only_telecom=True)` = `pending_cases.get_pending_cases` ثم الفرز على **المدعية فقط** (الجزء قبل «ضد»؛ إن لم يتضح الفصل: `case_db.get_case` ← `api.parse_case_info` بالتتابع). `only_telecom=False` = كل المتداولة بلا جلب إضافي (company فارغة لغير الاتصالات). بلا كاش/تزامن؛ «تحديث» يعيد الجلب. **لا حقل تاريخ انتهاء على القضية** (يُحسب لاحقاً لكل عقد: بداية العقد + مدة الالتزام).
- `qt_expert_reports.py`: `ExpertReportsPage` (بطاقات، زر تحديث، مفتاح «قضايا الاتصالات فقط»/«كل القضايا» يُحفظ في `expert_reports_prefs.json`؛ زر الشركات حُذف) + `CaseDetailDialog` (بيانات القضية + زر «ابدأ كتابة تقرير» مفعّل منذ 2أ/2ب) + `ReportProgressDialog` (شريط المراحل: جلب/تحويل/قراءة/كتابة، خيط خلفي، زر «فتح المجلد»).
- `qt_shell_v2.py`: بند `expert_reports` تحت «عملي». الاختبارات: `python -W ignore -m unittest test_telecom -v`.
- `case_workspace.py` (2أ): `ensure_workspace(case, root=None)` ينشئ `{الجذر}\{رقم الخبرة}\` + `00_نظام/01_اصول/02_markdown/03_حقائق/04_تقرير` + `case.json` (الناقص فقط، لا يكتب فوق شيء). الجذر من `expert_settings.load_reports_root()` (بطاقة «مجلد تقارير الخبرة» بالإعدادات) وافتراضياً `Desktop\تقارير الخبراء`. `write_case_json` ذرّي (mkstemp→fsync→os.replace) مع `case.json.bak` (لا تُستبدل .bak سليمة بنسخة تالفة)، `read_case_json` يرجع لـ.bak عند التلف. `check_path_lengths`: أطول مسار + هامش 80 ≤ 260. case.json: `caso_no, autocase_no, claim_no, case, stages{key:{state,message,at}}, files{}` (files لبصمات 2ج).
- `report_pipeline.py` (2ب): `Stage(key,label,run,depends)` + `Pipeline(base,data,stages,on_update).run()`؛ الحالات pending/running/done/failed/blocked/unavailable. الفشل لا يوقف المستقل، والمعتمد يصبح blocked؛ `running` المتبقية من إغلاق مفاجئ تُعاد pending. `default_stages()` بلا دوال بعد ← «قيد التنفيذ».
- الاختبارات: `python -W ignore -m unittest test_case_workspace -v` (بيانات `test_data/dummy_case.json`، تشمل قتل عملية فعلية أثناء مرحلة ثم الاستئناف).

## ملفات أخرى
- **ma7dar_template.dotx / اخطار_حكومه.dotx** — قوالب Word (مُضمَّنة داخل EXE عبر --add-data).
- **ExpertApp.spec** — بناء PyInstaller (نظام_الخبراء.spec القديم منقول). **Installer.iss** — Inno Setup (VC++ Redist + WebView2).
- **سكربتات مستقلة:** نُقلت كلها إلى `قديم/cleanup-2026-10-17/` (list_my_cases, check_referrals_2026, gemini_setup, auto_captcha, demo_extraction, dev_track_demo, make_desk_icon, ai_reader, qt_sessions_page_v2). `build.py` باقٍ لأن مهارة /release تشغّله.

---

## ⚠️ مبادئ ودروس مهمة (لا تُنسى)
- **ملفات كاملة فقط** — لا diffs جزئية. **موافقة صريحة قبل أي تعديل.** **Revert أولًا ثم debug.**
- **أوامر تشخيص سطر واحد** (`python -c "..."`)، لا ملفات تشخيص على القرص.
- **stale snapshot:** استخدم آخر نسخة يرفعها الخبير، لا الأصلية القديمة.
- **الكشف باللون هش** — يُفضّل تحليل نص `ECS_CASE_FLOW`. **`__pycache__` يخفي التحديثات.**
- **METMONTH يتطلب POST مسبق** لـ set_sourc.php. **لا حفظ في DB بدون مفتاح Gemini.**
- **التخويل بالاسم لا برقم الحساب** (الرقم غير موثوق). **مساحة عمل Copilot تتصفّر بين المهام** — الأصل الموثوق `ExpertApp.zip.txt` المرفوع.

---

## 📌 قيد العمل (يُتابَع في PROJECT_MEMORY.md قسم 8/9)
- استبدال ملفات ميزة الصلاحيات + إعادة بناء EXE + اختبار حي بالدوام (Supabase جاهز ✅).
- اختبار صفحة القضايا المحالة (`referred_cases.py`) على قضية حقيقية (task_id + الأعمدة + صف الاستعانة 130049).
- تحديد اللون `#0e5480` · اختبار `_ensure_next_session` على قضية جديدة فعلية.

### 🎨 شاشة قائمة «تقارير الخبراء» (شكل جديد من design/)
- `qt_report_card.py`: كل الشكل (ثوابت الألوان، `StatCard`، `ReportCaseCard`، `steps_strip`/`step_dot`، `load_plex()`). البطاقة: رقم الخبرة + الشركة، «المدعي» و«المدعى عليه» سطران، شريط 7 نقاط، سطر «ما ينتظرني». الشريط الجانبي: أزرق/عنبري (خطوة تحتاج مدخلاً)/أحمر (خطوة فاشلة). لا رقم آلي ولا استلام ولا جلسة ولا نسبة.
- `reports_list_model.py`: منطق صرف. `resolve_parties` (الأولوية: ما جلبه النظام ← case_db المحفوظ ← العنوان «س ضد ص»؛ العنوان اسم واحد بلا «ضد» لا يُنسب لدور ويظهر «الأطراف:»)، `step_states`/`step_hint` (قراءة case.json بترتيب العرض: الموضوع، المأمورية، الإجراءات، المستندات، البحث، النتيجة، المرفقات)، `build_card/kpis` (القضايا النشطة، قيد الإعداد، تنتظر إجراءً مني)، `search`.
- `qt_expert_reports.py`: `ExpertReportsPage` — الصفحة كلها داخل QScrollArea واحدة (العنوان والمؤشرات والفلاتر تتمرر مع البطاقات). البطاقة تفتح `CaseDetailDialog._start_report` (المسار كما هو).
- الاختبار: `python -W ignore -m unittest test_reports_list_model -v`. (اللقطة reports_list_screenshot.png منقولة إلى `قديم/cleanup-2026-10-17/`.)


## 🔧 مسار القضية — إصلاحات السلوك (2026-10-17)
- `case_procedures.py`: الخطوة لا تكتمل (`done`) إلا بالثلاثة: **تاريخ الاستلام** (`case.received_date` ثم «توزيع للخبراء» لي بسجل الحركة) + **تاريخ الحجز** (آخر جلسة «حجز…» بـ`ECS_CASE_FLOW` أو بعنوان جلسة التقويم) + **حضور كل الأطراف في محضر واحد** (`analyze_attendance`: قواعد ← JSON بالذكاء `ai_attendance` ← تأكيد الخبير `confirm_attendance` مربوط ببصمة المحضر). الجلسات = التقويم `load.php` ∪ سجل الحركة (`flow_fetcher`/`parse_flow_actions`/`merge_sessions`)، **قائمة فارغة ≠ نجاح** (تُجرَّب البدائل ثم needs_input «تعذّر التحقق»). `build_checks`/`checks_text` = قائمة التحقق + «جلسات النظام N مقابل محاضر موجودة M». النتائج في `case.json['procedures']`.
- `qt_review_dialogs.py`: `SubjectReviewDialog` (نص كامل + «اعتماد»)، `ProceduresDialog` (قائمة التحقق + تأكيد الحضور + زر الذكاء)، `show_saved_toast`. `qt_mission_dialog.py`: زر «اعتماد».
- `case_model.py`: `reviewed→done` مسموح (تعديل بعد الاعتماد ← «كُتبت»)، `FEEDS` (تعديل الموضوع/الإجراءات ينبّه البحث/النتيجة)، `stale_labels()`، **لا اعتماد للمرفقات على غيرها**.
- `case_attachments.py`: `sync_attachments` آلي (يُستدعى من `reload` ومن `case_documents`): «عدد ( N ) محضر أعمال.» ثم «حافظة مستندات {مقدِّمها} بتاريخ {DD/MM/YYYY}» (+«عدد ( n ) {نوع}.»). العبارة من التقرير النموذجي بـ`samples/`.
- `report_docx.py`: الإصدار يعمل بأي مرحلة، الناقص `[يُكتب]` (`TODO`)، الملفات `التقرير_v1.docx` ثم `_v2`… ولا يُستبدل شيء؛ `case.json['report']={file,version,at,warnings}`.
- `case_documents.py`: `add_files` (نسخ + بصمة `src_sha1` داخل الحافظة) ← `process_pending` (يحوّل الجديد فقط، `stop`) ؛ `classify_files`، `recover_running`، `reconvert` (للفاشل فقط). `qt_documents_dialog.py`: ملفات/مجلد، حالة لكل ملف، لوحة «ما يفعله البرنامج الآن» يسار، لون لكل حافظة (`portfolio_colors`)، **Job خلفي** بسجل `_JOBS` يبقى بعد الإغلاق (`live_data(base)`)، سؤال الإغلاق «إيقاف أم خلفية». `ocr_engine.py`: خيوط ONNX = نوى−2.
- الاختبارات: `python -W ignore -m unittest test_case_procedures test_case_attachments test_case_documents test_report_docx test_qt_case_track test_qt_documents_dialog test_qt_review_dialogs -v` (219 اختباراً مع بقية مجموعة المسار). نسخة احتياطية قبل التعديل: `قديم\backup-fixes-20261017\`.

## 📞 الموضوع بصيغة الاتصالات (2026-10-17)
- `case_subject_telecom.py` (منطق صرف): `telecom_company(row, case, companies)` (المدعية من case_db ثم القضية ثم عنوانها عبر `telecom_config.match_company` على `[telecom_companies]`) ← `build_subject(plaint_text, defendants, ask)` = طلب JSON من النموذج (`build_prompt`) ثم **تحقق الكود**: `Plaint` يرمّز النص (أرقام بقيمة Decimal لا بشكلها، إهمال التشكيل/الترقيم/تنوين الفتح) و`verify(kind, value, plaint)` يشترط ورود القيمة **متصلةً** في الصحيفة وأرقامها موجودة وموجبة، والمكتوب في الموضوع هو **نص الصحيفة** لا نص النموذج؛ ما لم يتحقق = `TODO` («[يُكتب]»). `defendant_kind` (جمع إن تعدد؛ شركة ← مؤنث؛ وإلا من «المدعى عليه/عليها» في الصحيفة نفسها؛ لا تخمين من الاسم، والافتراضي المذكر مع تنبيه). `compose` = القالب الثابت (عدة عقود: «وعقد آخر مؤرخ …» و«للعقد الأول/الثاني»). `fetch_claim_text(cookies, autocase_no)` = `documents.get_claim_for_case` ثم نص PDF (fitz، وOCR الداخلي للممسوح).
- `case_subject_mission.run_subject(base, data, get_case, force, ask, claim_fn, companies)`: قضية اتصالات ← `_run_subject_telecom` (كاملة `done`؛ ناقصة أو بلا صحيفة/اتصال `needs_input` والنص محفوظ؛ فشل الجلب/الذكاء `failed` وتُعاد المحاولة)، وغيرها على ملخص الصحيفة كما كان. `qt_case_track._do_subject` يمرّر `ask` و`claim_fn` (عند وجود cookies). `qt_review_dialogs.SubjectReviewDialog` ينبّه إن بقي «[يُكتب]» والاعتماد بزره فقط.
- الاختبارات: `python -W ignore -m unittest test_case_subject_telecom test_case_subject_mission test_qt_review_dialogs test_qt_case_track -v`. نسخة احتياطية قبل التعديل: `قديم\backup-subject-telecom-20261017\`.

## 🗂️ تصنيف المستندات وتوجيهها عند الإضافة (2026-10-17)
- `doc_router.py`: `classify_file` (OCR المحلي للصفحة الأولى فقط ← `classify_text` بالقواعد من `[doc_types]` في gemini_network.ini، كلمات مفصولة بـ`|`؛ الثقة = حصة النوع الفائز × min(1، تطابقاته/2)، دون `[doc_classify] min_confidence` (0.5) أو تعادل = «غير معروف»). الأنواع: حافظة مستندات | مذكرة دفاع | محضر أعمال | صحيفة دعوى | حكم | غير معروف. `engine_for(type)` من `[doc_routing]` (local | external_ocr | gemini): الافتراضي مذكرة←external_ocr، حافظة←gemini، والبقية local؛ غير المعروف بلا محرّك.
- حدود Gemini في `[gemini_limits]` (max_pages=1000، max_mb=50، verified=2026-10-17، source) — من ai.google.dev/gemini-api/docs/document-processing و/files؛ `chunk_pages` إعداد التطبيق (0=معطّل) لا حدّ من Gemini. `plan_chunks` (pypdf) يقسّم بالتنصيف حتى يوافق الحدّين، `gemini_engine` يرسل كل جزء بعلامة فصل صفحات ويدمج بـ`<!-- صفحة N -->` بالترقيم الأصلي (عدد صفحات الردّ ≠ الفعلي ← تحذير ونص مدموج). `ensure_defaults()` يضيف الأقسام الناقصة فقط.
- `external_ocr_engine` = ocr_space المضبوط؛ غير مضبوط/فشل ← المحلي + تحذير. Gemini غير متاح ← المحلي + تحذير. التحذير يُحفظ في `doc['warning']` وأول سطر في الـmd.
- `case_documents.py`: `add_files` يصنّف كل جديد ويسجّل في case.json لكل مستند: `doc_type, type_conf, type_reason, first_text, engine, manual, needs_type`؛ `needs_type` يُحجز من `pending_docs` (والخطوة needs_input) حتى `set_doc_type`. `set_doc_type/set_doc_engine` (pending/failed فقط). `CLASSIFIER` و`ENGINES` قابلان للاستبدال بالاختبارات؛ `convert=` الصريح (قديم) يتجاوز المحرّكات.
- `qt_documents_dialog.py`: مرحلتان — «إضافة وتصنيف» ثم تعديل القائمتين (نوع المستند/المحرّك) ثم «استيراد وتحويل»؛ `FirstPageDialog` للمجهول (صورة الصفحة الأولى + الأنواع).
- الاختبارات: `python -W ignore -m unittest test_doc_router test_case_documents test_qt_documents_dialog -v`. نسخة احتياطية: `قديم\backup-doc-routing-20261017\`.

## 📄 صفحة القضية (2026-10-17) — بديل نافذة المسار
- `qt_case_page.py`: `CasePageDialog` **يرث** `qt_case_track.CaseTrackDialog` (كل `_do_*` و`_run_bg` و`_do_report` و`_review` كما هي) ويستبدل الشكل فقط: رأس (رجوع «تقارير الخبراء» + رقم القضية + `parties_line`) ← `StepperWidget` (سبع خطوات من `reports_list_model.step_states`، الضغط يفتح الخطوة) ← بطاقة بيضاء لمحرّر الخطوة المفتوحة (`_card_<key>`) ← شريط: السابق | الأسئلة المهمة (`QuestionsDialog` → `case.json['questions']`) | إصدار التقرير (Word) | «اعتماد والانتقال». حفظ تلقائي بعد 1.2ث عبر `set_subject`/`set_mission`/ملف البند/`case_conclusion._save`.
- دوال صرفة: `step_list`, `current_step` (المرفقات لا تُفتح أولاً)، `neighbour`, `contracts`, `docs_split`, `tag_colors` (عنبري للمدعية، تيل للمدعى عليه).
- `qt_expert_reports.CaseDetailDialog._start_report` يفتحها. الاختبار: `python -W ignore -m unittest test_qt_case_page -v`. لقطات: `case_page_screenshot.png`, `case_page_documents_screenshot.png`. نسخة احتياطية: `قديم\backup-case-page-2026-10-17\`.

## ⚙️ «الإجراءات» تلقائية + الموضوع بصيغة العقد العام + «إعادة الكتابة» (2026-10-17)
- `case_procedures.py` (أُعيد تنظيمه، المنطق القديم نفسه): `find_minutes` يأخذ المحاضر دون سؤال من `expert_settings.load_minutes_root()` (افتراضياً `Desktop\محاضر`؛ مجلد `{رقم الخبرة}` + أي ملف/مجلد في الجذر يحمل رقم الخبرة + سطح المكتب مع الجذر الافتراضي + `01_اصول\محاضر` داخل مجلد القضية لما يضيفه الخبير). الأنواع `MINUTE_EXTS` (docx/pdf/صور/md/txt)، الإخطار و`~$` لا يُحسبان، `3.docx`+`3.pdf` = محضر واحد. `read_minute_text` (docx XML، pdf نص ثم OCR داخلي، صور OCR) + ذاكرة `minute_texts`. `compare_minutes`: الربط بالرقم ثم بتاريخ المحضر (`minute_date`) ← `missing`/`missing_count`/`missing_dates`.
- الحضور `analyze_attendance`: لكل طرف — قواعد، ثم **طلب ذكاء واحد** بكل نصوص الحضور لمن لم تجده القواعد (مخزّن ببصمة النصوص)؛ الغياب «مؤكد» فقط إن قرأه الذكاء أو كانت النصوص فارغة/«لم يحضر أحد»، وإلا «لم يتأكد» (لا تخمين). `set_attendance` (تعديل الخبير: حضر/لم يحضر/تلقائي) مربوط باسم الطرف. `confirm_attendance` بقيت للتوافق فقط.
- النص `compose_text` = `PROCEDURES_TEMPLATE` من تقرير النموذج `samples\…H2212338.docx` حرفياً (الاستلام/الحكم التمهيدي/جملة الحضور/الحجز، الناقص «[يُكتب]»)؛ `attendance_clause` («حضرتها الشركة المدعية وتخلف المدعى عليه عن الحضور رغم صحة إعلانه»…)، `party_labels` (الشركة مؤنث، تعدد = الأول/الثاني). `set_procedures_text` (تعديل الخبير؛ بعد الاعتماد يبقى معتمداً و`mark_modified`).
- الحالة `re_evaluate`: **reviewed تلقائياً** فقط بالأربعة (الاستلام + الحجز + الحضور مستخرج + عدد المحاضر = الجلسات)، وإلا needs_input برسالة «ينقص: …». `build_checks`/`checks_text`/`missing_line`/`summary_line` («تم الاطلاع على N محضر»، `count_word`). إعادة التشغيل لخطوة معتمدة لا تمرّ بـrunning ولا تُقدِّم قِدَم البحث إلا إن تغيّر النص. `add_minute` (أي نوع ← مجلد القضية)، `exclude_minute`، `all_candidates`.
- `qt_review_dialogs.MinutesEditDialog` («تعديل»: استبعاد/إعادة محضر + حضور كل طرف) بدل `ProceduresDialog` (حُذفت). `qt_case_track.actions_for('procedures')` = «إضافة محضر آخر» + «تعديل» فقط؛ `_ask_for(purpose)` يغلّف المزوّد بـ`ai_call_log`.
- `case_subject_contract.py` (جديد): صيغة العقد العام لغير الاتصالات «جاءت المدعية بصحيفة مفادها أنها بموجب عقد مؤرخ … وذلك مقابل مبلغ … لمدة …. وأفادت المدعية – على حسب دعواها – أنها … إلا أن المدعى عليه أخلّ في …، فتم رفع الدعوى الماثلة.» بمنهج التحقق الحرفي نفسه (`case_subject_telecom.verify` + نوع `excerpt`). `case_subject_mission._run_subject_formula(… formula)` للصيغتين؛ **لا ملخص حر** (`case_summary` لم يعد يُستخدم للموضوع).
- `ai_call_log.py` (جديد): `wrap(ask, purpose)` يسجّل كل استدعاء (الغرض/المزوّد/المدة/النتيجة أو الخطأ) في `%LOCALAPPDATA%\ExpertAppi_calls.log` + آخر 50 بالذاكرة (`last`/`describe`)؛ `case_research.default_ask` يضبط اسم المزوّد (`set_provider`).
- `qt_case_page.py`: فتح «الإجراءات» يشغّلها وحدها (`_auto_procedures`، مرة لكل فتح، `AUTO_PROCEDURES` يُطفأ بالاختبارات) ونافذة الملف فقط إن لم يوجد محضر؛ البطاقة: سطر الملخص + قائمة التحقق + محرّر النص + «إضافة محضر آخر»/«تعديل». «إعادة الكتابة» = `force` (`_rewrite`/`_rewrite_item`) مع شريط «⏳ جارٍ…» داخل البطاقة ثم `_notice` (نجاح + المزوّد، أو «تعذّرت إعادة الكتابة: …»). الشكل: `_Connector` (خط 1px مرسوم بلا خلفية)، `_fit_to_screen` (النافذة لا تتجاوز الشاشة)، الشريط السفلي RTL (السابق يميناً، الاعتماد يساراً، لا يُضغط زر). إعداد جديد «📁 مكان حفظ المحاضر» (`save/load_minutes_root`) تستخدمه `qt_sessions_page` أيضاً.
- الاختبارات: `python -W ignore -m unittest test_case_procedures test_case_subject_contract test_qt_case_page test_qt_review_dialogs test_qt_case_track -v` (359 إجمالاً). لقطات: `case_page_procedures_100.png`, `_125.png`, `_150_small.png`. نسخة احتياطية: `قديم\backup-procedures-auto-20261017\`.

## 🔎 فحص الجاهزية قبل «البحث ورأي الخبرة» (2026-10-17)
- `case_readiness.py` (جديد): لكل نقطة من المأمورية المؤكَّدة `check_point` ← النموذج يستنتج «ما يلزم» ويقترح موضعاً + اقتباساً حرفياً؛ الكود يحكم: `locate` (اقتباس ≥3 كلمات متصل في نص مستند محوَّل بتطبيع `case_subject_telecom.Plaint`) ← موضع «حافظة/مستند/صفحة» (`where_text`) وإلا «ناقص» (`claimed=True` إن ادّعى النموذج موضعاً لم يُثبت). الفهرس `doc_index` من case.json + 02_markdown (صفحات `<!-- صفحة N -->`/`--- صفحة N ---`). الناتج `data['readiness'] = {items:[{id,n,state ready|missing|error,score%,requirements,missing}], docs_sig, points, added, closed}`.
- الأسئلة: `sync_questions` ← `data['questions']` سجلات `{id,auto,point_id,point_n,to,need,why,text,status open|closed,closed_by}` (النصوص اليدوية القديمة تُحوَّل `normalize_questions`)؛ الصياغة `question_text` «تكليف {المدعى عليه} بتقديم {…}، وذلك لازم للبند (n) من المأمورية «…»؛ إذ …». إعادة الفحص تُغلق ما سُدّ وتُبقي الباقي. `questions_html` للطباعة.
- جدول الوقائع `03_حقائق/جدول_الوقائع.md` (`facts_table`: كل رقم ≥3 خانات/بكسر/بفواصل بموضعه). `case_research._write_item` يمرّر الجدول للنموذج ويستبدل أي رقم خارجه بـ«[رقم غير موثّق: X]» (`mark_unverified_numbers`).
- `case_research.run_research(only=…)` للجاهزة فقط (الباقي ← needs_input «بانتظار مستند»)؛ `rewrite_item(missing=…)` = «اكتب رغم النقص» (علامة «[ناقص: …]»، يضمنها الكود، `written_with_missing`).
- `qt_case_page`: خطوة البحث تبدأ ببطاقة «الجاهزية» (`_readiness_block`): لكل بند جاهز/ناقص ودرجته و`case_readiness.sentence` + «بانتظار مستند» + «اكتب رغم النقص»؛ «كتابة البحث ورأي الخبرة» (`_write_ready`) و«فحص الجاهزية من جديد». فحص تلقائي عند فتح الخطوة وعند تغيّر بصمة المستندات (`is_stale` في `reload`)، `AUTO_READINESS`. `QuestionsDialog` تعرض البند والحالة + «طباعة».
- الاختبارات: `python -W ignore -m unittest test_case_readiness -v` (368 إجمالاً). نسخة احتياطية: `قديم\backup-readiness-20261017\`.

- **qt_context_menu.py** — قائمة سياق موحّدة (`install`, `build_menu`). **doc_router.py** — `best_engine`, `text_quality`, `quality_warning`. **case_subject_telecom.py** — `find_date`, `fix_ocr`, `contract_ref`. **case_subject_contract.py** — `link_for`.

## 🧾 الدفعة الأخيرة (2026-10-17): المبالغ والمحركات ومزوّد كل مهمة والاعتماد التلقائي
| ملف | وظيفته |
|---|---|
| `amounts.py` | كلمات عربية ↔ Decimal (دينار/فلس)؛ `reconcile(رقم، حروف)` ← verified / mismatch (لا يُكتب أيٌّ منهما) / digits_only / words_only؛ `fmt_kwd` → «5,876.540 د.ك». يُستدعى من `case_subject_telecom.verify` (kind=amount\|claim) ويرجع `alerts` (red/amber) إلى `data['subject_alerts']`. |
| `ocr_vision.py` | Google Cloud Vision (DOCUMENT_TEXT_DETECTION) بمفتاح API للخبير (`vision_key.json`)؛ بطاقة في الإعدادات؛ محرّك `doc_router.ENGINE_VISION='cloud_vision'`. |
| `doc_router.py` (إضافات) | `read_numbers_pdf` (Gemini ← Vision ← OCR.space ← طبقة نصية ← محلي، مع أسباب التخطي)، `engine_alert`، `step_alerts`، `vision_engine`، دفعات Gemini `batch_pages` وإعادة المحاولة عند 429 (`_call_provider_retry`). |
| `ai_providers.py` (إضافات) | `TASKS/TASK_DEFAULTS/PURPOSE_TASK`، `build_task_chain`، `ProviderMissing`، `set_override/pop_missing`، `[task_providers]` في ini. |
| `case_autoreview.py` | يعتمد الموضوع/المأمورية/المستندات/المرفقات وحدها متى اكتملت. |
| `qt_bidi.py` | عزل التواريخ والأرقام و«[…]» للعرض فقط (`BidiPlainTextEdit`، `isolate_tokens`). |
| `window_guard.py` | حارس النافذة الرئيسية عند إغلاق الحوارات + خروج صريح. |
| `case_procedures.py` | `minutes_complete`، `attendance_clause(result, complete, reason)`، `DISCUSSED`. |
| `case_documents.py` | `text_fingerprint`، `find_text_original`، `content_docs` (مراجع md/txt المكررة `ref_of`). |
| `report_docx.py` | `resolve_header`، `remember_header` (المحافظة/القسم). |
| `secret_audit.py` | يفحص مفاتيح API بنص صريح (ini، ai_providers_cache.json، ملفات مفاتيح الخبير) ويولّد نص تحذير الإعدادات؛ لا يعرض قيماً. |
| `gemini_config.py` (إضافات) | `prepare_pdf(critical)`، `get_critical_color`، `generate_from_pdf(critical, task)`، `last_read()`. |

## 🔒 ملخص الدفعتين الأخيرتين (2026-10-17): الحاسم والأسرار والمبالغ (مرجع سريع)
- **تحضير الممسوح للحاسم:** `gemini_config.prepare_pdf(critical=True)` صور دائماً (ولو بطبقة نصية) بـ300dpi وجودة 90؛ القيم في قسم `[pdf]` بملف `gemini_network.ini`: `critical_dpi`، `critical_jpeg_quality`، `critical_max_mb` (30، تحت حدّ Gemini 50MB؛ تجاوزه يخفض dpi حتى 150 ثم الجودة)، `critical_color` (gray\|rgb). غير الحاسم 150dpi رمادي جودة 70.
- **حكم الإحالة:** `case_info_window.extract_from_pdf` ← `generate_from_pdf(critical=True)`: Gemini أولاً ثم المسار المعتاد؛ `gemini_config.last_read()` + `case_info_window.judgment_engine_json()` ← عمود `case_db.judgment_engine` (JSON)؛ تنبيه أحمر في بطاقة المأمورية عبر `doc_router.step_alerts(data,'mission')`.
- **summarizer.py:** `generate_from_pdf(..., task='summarize')` ← جدول «مزوّد كل مهمة» (`auto` = السلاسل القديمة).
- **ExpertApp.spec:** فلتر أسرار على `a.datas` (أي `.ini` من مجلد المشروع + أسماء `gemini_network.ini`، `ai_providers_cache.json`، `*_key.json`، `credentials.json`…) مع `assert` يفشل البناء؛ كاش المزوّدين في `%LOCALAPPDATA%` خارج المثبّت.
- **secret_audit.py + بطاقة التحذير:** `qt_settings_page._build_secrets_warning` تظهر عند وجود مفاتيح بنص صريح (بلا عرض قيم).
- **amounts.py:** محلل مبالغ عربي (Decimal، دينار/فلس 3 خانات) والتحقق رقم↔حروف؛ **window_guard.py:** حارس الرئيسية عند إغلاق الحوارات؛ **qt_context_menu.py:** قائمة السياق بخط IBM Plex Sans Arabic (يُسجَّل من `qt_report_card.load_plex()` عند الإقلاع في main.py).
- **⏳ المتبقي:** الملخص.md · العقود وآلة الحساب · البحث ورأي الخبرة · تبسيط نافذة المستندات · نقل المفاتيح إلى Windows Credential Manager (مقترح غير مطبَّق).

## ✍️ دفعة «أسلوب الموضوع» (2026-10-17)
| ملف | وظيفته |
|---|---|
| `case_subject_ai.py` | كتابة الموضوع بالذكاء: حقائق JSON ← تحقق (تواريخ/مبالغ/أرقام/عبارات) ← few-shot من `نماذج_صياغة_الموضوع.md` (مجلد بيانات الخبير) ← فحص «لا رقم غير متحقَّق» ← تركيب حتمي احتياطي. `add_model`، `pick_models`. |
| `case_subject_mission.py` | `STYLE='ai'` (الافتراضي)، `_finish_ai_subject`، `data['subject_missing']`. |
| `case_subject_telecom.py` | `parse_date/find_date/plaint_dates/fmt_date` (مائلة عكسية، هندية، مقلوبة 201814119 بعد «مؤرخ»، 1990–2030)؛ `fetch_claim_text(..., base, data, refresh)`. |
| `case_sources.py` | حفظ الصحيفة والحكم في `حكم_الإحالة\`/`صحيفة_الدعوى\` (case_folder، بلا استبدال) ونص القراءة في `00_نظام\مصادر\` وتسجيلها في `case.json['sources']` (تاريخ الجلب، المحرك، البصمة، نص الصحيفة)، البحث محلياً أولاً، `adopt_judgment`، `refresh_judgment`. |
| `case_questions.py` | الأسئلة المهمة بالذكاء: `expert_tasks` و`party_requests`، `concise`، ترشيح الممنوع، `merge`، `questions_html`. |
| `qt_case_page.py` | `QuestionsDialog` بجدولين؛ أزرار «احفظ هذا النص كنموذج» و«تحديث الصحيفة/حكم الإحالة من النظام». |
| `reports_list_model.py` | `has_gaps`، `attachments_complete` (✓ صادقة). |

## 📁 مجلد القضية هو الأصل (2026-10-18)
`{الجذر}\{رقم الخبرة}\` — الجذر من الإعدادات، افتراضياً `Documents\تقارير الخبراء` (`case_workspace.default_root`؛ القديم `Desktop\تقارير الخبراء` يُنسخ منه عند الفتح).
```
محاضر/  حكم_الإحالة/  صحيفة_الدعوى/  مستندات_أخرى/  تقارير_سابقة/   ← الأصول (لا حذف ولا استبدال)
markdown/<نفس البنية>.md + .manifest.json                          ← مشتق، لا يُعدَّل يدوياً
00_نظام/ (مصادر/*.txt، ترحيل_المجلد.log)  03_حقائق/  04_تقرير/  case.json
01_اصول/ 02_markdown/                                               ← قضايا قديمة (تُقرأ، لا يُكتب فيها جديد)
```
| ملف | الدور |
|---|---|
| `case_folder.py` | `ensure_structure`، `add_original` (نسخ بلا استبدال، `NeedsFolder` لغير المعروف، تقصير الأسماء الطويلة)، `scan`/`load_manifest`/`save_manifest` (ذرّي)/`record_converted`، `sync_case_folder` → `{converted, failed, missing, total, message}` و`data['folder_sync']`، `latest_md`، `migrate_legacy`، `migrate_root`، `collect_local_minutes`، `fetch_from_system`، `open_case`، `adopt_manual_judgment`. `CONVERTER`/`CLASSIFIER` قابلان للاستبدال بالاختبارات. |
| `case_subject_mission.py` | `extract_mission`، `judgment_source`، `mission_source_changed`، `run_mission` (المجلد أولاً ثم case_db)، `refresh_mission_if_changed`. |
| `qt_case_track.py` | `sync_folder(fetch)` عند الفتح وبعد المستندات/المحضر المضاف/تحديث الحكم؛ سطر `folder_line`؛ `AUTO_SYNC`. |
- الاختبارات: `python -W ignore -m unittest test_case_folder -v`.

## 🔁 تحويل كل أصل + الفهرس + المحاضر + حكم الإحالة + إعادة الكتابة (2026-10-18)
| ملف | الدور |
|---|---|
| `case_convert.py` (جديد) | `convert(path, folder)` → (md، صفحات، محرّك). docx (فقرات+جداول+رأس الصفحة)، doc (Word COM ثم LibreOffice — `DOC_CONVERTERS`)، rtf (محلل داخلي)، odt، xlsx/xlsm (openpyxl)، csv، txt/md. PDF: `pdf_text_layer` إن كانت كل صفحة «سليمة» (`page_sound`: ≥40 حرفاً، لا رموز خطوط، `arabic_order_ok` ضد العربي البصري المعكوس، `doc_router.text_quality`) ← محرّك `text_layer`؛ وإلا `case_folder.legacy_convert` (المسار القائم جيميناي/OCR بحسب المجلد) مع إفصاح المحرّك في أول سطر. `FALLBACK` للاختبارات. |
| `case_folder.py` | `SUPPORTED = case_convert.SUPPORTED`؛ `is_ignored` (مؤقت) مقابل `is_temp` (+غير مدعوم)؛ `unsupported(base)`؛ المحوّل يرجع 2 أو 3 قيم (المحرّك في manifest `engine`)؛ **`count_check`** بعد كل مزامنة → `res['count']`/`data['folder_sync']['count']` = {originals, markdown, ok, unconverted[(اسم،سبب)], line}؛ `has_pending`؛ `open_case(..., ask)` يستدعي `referral_pick.pick`؛ الفهرس يُبنى بعد كل مزامنة. |
| `case_index.py` (جديد) | `فهرس_المستندات.md` في جذر مجلد القضية + `data['doc_index']`: لكل مستند الاسم/النوع/التاريخ/الأطراف/الصفحات/المسار، وجدول «العقود وملحقاتها» (أمر تغيير/أمر شراء/أمر عمل/ملحق عقد/عقد من الباطن/اتفاقية/عقد) بالتاريخ والأطراف والقيمة ورقم الصفحة. قواعد نصية فقط، الناقص «—». |
| `case_procedures.py` | **رقم المحضر من المحضر نفسه:** `minute_meta` (رأس Word `header*.xml` + المتن، أو طبقة PDF، أو md/txt) → `number_from_text`/`date_from_text`؛ `find_minutes` يعتمد رقم النص ثم الاسم (`no_source`، `no_conflict`)؛ الترتيب `minute_order_key` (التاريخ ثم الرقم)؛ `order_warnings` → `sessions['minute_warnings']` وسطور ⚠ في `build_checks`. `evaluate` يستدعي `case_minutes_ai`؛ `re_evaluate` لا يستبدل نصاً عدّله الخبير ويضع `procedures['changed_notice']`. |
| `case_minutes_ai.py` (جديد) | طلب واحد بنصوص كل المحاضر: رقم/تاريخ/حاضرون/متخلفون/ما جرى/انتقال/معاينة/شهود؛ `verify` لا يقبل إلا بدليل حرفي في نص المحضر نفسه والتاريخ وارد فيه؛ `merge_attendance` (لمن لم يتأكد فقط؛ الغياب إن نُصّ عليه في كل المحاضر)، `merge_extras`؛ `sessions['details']`؛ مخزّن ببصمة النصوص. |
| `referral_pick.py` (جديد) | `pick(base, data, ask)`: حكم النظام إن كان الأحدث ← وإلا أحدث مستند يحيل للخبرة بالترتيب التاريخي (`doc_date` من الاسم ثم «بجلسة/بتاريخ»، `court_level` تمييز>استئناف>كلية للتساوي) ← وإلا سؤال الذكاء بالقائمة ثم تحقق الكود (موجود + `extract_mission`). `data['judgment_pick']` {file, method system/auto/ai, note «حُدِّد تلقائياً، تأكد منه», reason}؛ `line(data)` للخط الأحمر؛ يُكتب في ذاكرة_القضية.md (قسم بيانات القضية). |
| `case_subject_mission.py` | `judgment_source` يبدأ بـ`judgment_pick`؛ `literal_check` → `mission['literal_missing']`؛ `set_mission` يضع `mission['edited']` (لا يُستبدل بحكم جديد ← flagged)؛ `subject_facts` و`subject_edited`. |
| `case_rewrite.py` (جديد) | «إعادة الكتابة»: `rewrite_subject`/`rewrite_procedures` يرسلان الحقائق + النص الحالي لمزوّد الصياغة؛ `foreign_numbers` يرفض أي رقم غير وارد (محاولتان)؛ `is_manual(data, key)`. |
| `qt_case_page.py` | حُذفت «نوع القضية…» و«احفظ هذا النص كنموذج» و«تحديث الصحيفة من النظام» (الدوال باقية)؛ النوع يُسأل مرة واحدة إن لم يتضح (`AUTO_ASK_TYPE`, `subject_type_asked`)؛ `sync_folder(fetch=True)` عند الفتح (`AUTO_SYNC`) + `folder_line`؛ سطر «ناقص: …» أحمر (`_missing_line`, `subject_missing_text`)؛ المأمورية: زر صغير «أعد القراءة من الحكم» + خط الحكم المحدَّد تلقائياً + عدم الحرفية؛ الإجراءات: «إعادة الكتابة» + `changed_notice`؛ `_rewrite` يطلب تأكيداً للنص اليدوي ويزامن أولاً إن وُجد جديد (`_pre_rewrite_sync`)؛ `pick_line` تحت الأطراف. |
| `qt_case_track.py` | `sync_folder` يمرّر ask، ومحضر جديد مُحوَّل ← `case_procedures.evaluate`؛ `_show_folder_line` (أحمر عند اختلاف العدد). |
- الاختبارات: `python -W ignore -m unittest test_folder_minutes_referral -v` (23). نسخة احتياطية: `قديم\backup-folder-procedures-20261018\`.

## 🧩 دفعة الأجزاء الخمسة (2026-10-18)
| ملف | الدور |
|---|---|
| `case_folder.py` | `brief_status(fs)` → {line «تعذّر تحويل N ملفات», details[(اسم، سبب)], bad}، `files_word`، `details_text`. |
| `qt_case_track.py` | `_make_folder_row` (السطر + «التفاصيل» + «أعد المحاولة»)، `folder_details_text`؛ `auto_resume_documents` (`AUTO_RESUME`) + إجراء `resume`؛ `AUTO_CONTRACTS` ← `case_contracts.extract` بعد كل مزامنة. |
| `qt_documents_dialog.py` | «إضافة مستندات القضية»: `AUTO_RUN` (السحب/الاختيار ← نسخ+تصنيف+تحويل)، `add_paths`، `progress_model`/`_refresh_progress` («N من M» + شريط + نسبة كل ملف)، `_ask_unknown_once` + `UnknownKindsDialog`، `_portfolio_edited`؛ دوال الوحدة `convert_work`/`_run_pending`/`resume_documents`. الإغلاق بلا سؤال. |
| `case_documents.py` | `content_meta`/`apply_content_meta` (نوع/تاريخ/أطراف من الصفحة الأولى)، `CONTENT_KIND_LABELS`، `suggest_portfolio`، `update_portfolio`، `unknown_kind_docs`/`set_kinds`، `batch_progress`، `resumable`؛ تقدّم الصفحات عبر `_TLS` و`doc_router.PAGE_HOOK`. |
| `doc_router.py` | `PAGE_HOOK` + `page_progress(done, total)` (OCR المحلي صفحةً صفحة، Gemini جزءاً جزءاً). |
| `case_contracts.py` (جديد) | `collect`، `build_prompt`، `verify` (`date_in_text`/`amount_in_text` حرفياً، `decide_scope`)، `extract` (ببصمة النصوص)، `render`/`write_file` ← `العقود.md` + الفهرس، `subject_context`، `main_contract_facts`. النطاقات `SCOPE_IN/MAIN/OUT`. |
| `case_subject_ai.py` | `build_subject(..., contracts=data)` + `with_contracts` (العقود المتحقَّقة بين الطرفين في الطلب وحقائق العقد). |
| `case_index.py` | `render(rows, caso_no, ai)` يضيف جدول العقود المستخرجة. |
| `qt_case_page.py` | زر «إضافة مستندات» في الرأس (`add_docs_btn`)؛ تبويب العقود مجمّع بالنطاق مع الأحمر لغير المتحقَّق (`contract_text`/`_contract_row`)؛ `docs_split(data, base)` و`content_title` بالمحتوى؛ «استئناف». |
| `case_minutes_ai.py` | حقل `booking` في الطلب + `booking_date_in`، `booking_by_rules`، `booking_from_minutes` ← `procedures['booked']` «مأخوذ من المحضر رقم X» (في `case_procedures.evaluate`). |
| `expert_settings.py` | `case_minutes_dir(caso)` (الكتابة)، `minutes_read_dirs` (قراءة + القديم للتوافق). |
| `qt_settings_page.py` | `PathLineEdit`/`_path_edit` (استعراض المجلدات بالضغط)؛ بطاقة واحدة «مجلد حفظ مستندات القضايا». |
- الاختبارات: `python -W ignore -m unittest test_five_parts -v` (21).

## 📥 «إضافة مستندات القضية» داخل صفحة القضية (2026-10-18، تصميم Stitch)
- `qt_documents_panel.py` (جديد): `DocumentsPanel` يرث `qt_documents_dialog.DocumentsDialog` (المنطق كله: Job خلفي، نسخ ← تصنيف ← تحويل، الأسئلة) ويُعرض بعلامة `Qt.Widget` كأول تبويب «إضافة المستندات» في خطوة «المستندات والعقود». الشكل: (1) بيانات الحافظة: أزرار المقدّم المدعية/المدعى عليه/الخبير/أخرى + الحافظة + التاريخ، (2) منطقة إفلات + «اختيار ملفات/مجلد»، (3) صف لكل مستند (رقم، اسم، حجم، نوع، حالة ملوّنة بنسبة، إعادة المحاولة)، يساراً «ما يفعله البرنامج الآن» (خط زمني: تم/جارٍ بشريط نسبة — متحرك للمحرّكات البعيدة بلا نسبة/بانتظار)، أسفل «مجموع المستندات • جاهز للتقرير». `state_view`/`human_size` صرفتان. التنظيف عند الإتلاف `_teardown`.
- `qt_case_page.py`: زر الرأس «إضافة مستندات» و`do('documents','add')` يفتحان الخطوة لا نافذة؛ `_fit_docs_tabs` (+`resizeEvent`) يضبط ارتفاع التبويبات على المساحة المرئية فلا ينزل شيء تحت الشاشة؛ `_after_docs_panel` ← `sync_folder`.
- `case_documents.py`: `refine_portfolio(base, data, pid, ask)` بعد تحويل أول مستند يرسل الصفحة الأولى إلى مزوّد رخيص `CHEAP_SPEC='groq,openai'` (لا جيميناي) و`verify_portfolio_meta` يقبل المقدّم إن كان صفة معروفة أو وارداً حرفياً والتاريخ إن ورد في الصفحة؛ `portfolio['auto_meta']` (True اقتراح، 'ai' ضُبط، False عدّله الخبير فلا يُلمس). `DocumentsDialog.PORTFOLIO_ASK` للاختبارات.
- الاختبار: `python -W ignore -m unittest test_documents_panel -v`. `qt_documents_dialog.DocumentsDialog` باقٍ (اختباراته ومسارات قديمة).

## ✍️ «البحث ورأي الخبرة» و«النتيجة» بأسلوب الخبير (2026-10-20)
| ملف | الدور |
|---|---|
| `نماذج_صياغة_البحث.md` | مكتبة قابلة للتعديل (في `ExpertApp.spec`): «# القواعد» تُرسل مع كل طلب صياغة للبحث، «# قواعد النتيجة» مع طلب النتيجة، و«# النماذج» (18) بوسم `النوع:` اتصالات/مقاولة_توريد/باطن_شراكة/مرجعي/عام و`الكلمات:` علاقة/إخلال/حساب/اعتراضات/طلب_مستند/نتيجة. المرجعي من A2260789. |
| `drafting_library.py` | `RESEARCH_FILE`، `section(md, title)`، `load_section(name, title)`. |
| `calc.py` | الحساب بالكود فقط (Decimal): `D`, `q3`, `fmt/fmt_cur`, `Step(label, expr, value).line()`, `add_chain`, `subtract_chain`, `multiply`, `ratio`, `percent`, `convert(amount, rate, cur, date)`, `evaluate/formula` (ast آمن)، `contract_account` (جدول + diffs)، `sum_check`, `line_item_check`, `numbers_in`/`norm_num` (فحص الأرقام)، `currency_of`. |
| `amounts.py` | + `int_to_words`, `to_words(d)` («… ديناراً و… فلساً كويتي فقط لا غير»، مطابق ذهاباً وإياباً مع `words_to_decimal`؛ أضيف للمحلل «ألفاً/مليار/مائتا» و«دينار واحد/فلسان»). |
| `research_pipeline.py` | `state(data)`=`data['research2']`؛ `classify_point`/`group_points`/`axis_title`/`heading`؛ `party_labels`؛ `contract_groups` (+`contract_number`, `_assign_ids`)؛ `documents` (مراجع الخبير)، `minutes`؛ `assign_pages`/`_merge_docs`؛ `build_plan`؛ `axis_ready`؛ `facts_prompt`/`verify_facts`/`find_quote` (حقائق مشتركة لكل عقد `facts_cache`)؛ `requests_prompt`/`verify_requests`/`extract_requests`/`proven_requests`؛ `set_fx`، `compute`، `final_info`، `total_section_text`؛ `case_type`/`pick_models`/`section_material`/`draft_prompt`؛ `check_text` (رموز/ملفات/قوائم/ممنوع/صدى المأمورية/«لم يقدم» بلا سند/أرقام وحروف غريبة)؛ `prepare_section`، `draft_section`، `run(…, draft, despite_missing, only_axes, on_progress, stop)`، `rewrite_axis`، `merge_section/merge_all`، `set_section_text`، `merged_axes`، `research_text`، `notes_list`، `assemble`، `case_final`؛ `export_prompt`، `split_reply`، `import_reply`. الملفات: `04_تقرير/بحث/*.md`، `04_تقرير/البحث.md`، `04_تقرير/ملاحظات_البحث.md`، `04_تقرير/prompt.md`. حالات القسم: pending/blocked/facts/drafted/merged/failed. `MINUTE_TEXTS` للاختبارات. |
| `conclusion_pipeline.py` | `complete_axes`, `build_prompt`, `fix_paragraph`/`ref_of`, `parse_paragraphs`, `_enforce_financial`, `check`, `generate`, `accept_text`, `set_text`, `notes`, `render_md`/`text_of`؛ `data['conclusion']['v2']` + `04_تقرير/النتيجة.md`. |
| `case_conclusion.py` | `is_v2(data)` ← `run_conclusion`/`verify_counts`/`review_conclusion` توجّه للجديد. |
| `report_docx.py` | `_emit_research_v2` (المدموج فقط)، `_emit_conclusion` (لا نص مأمورية ولا «[يُكتب]» تحت النتيجة). |
| `qt_case_page.py` | `_card_research`: `_readiness_block` ← `_delivery_block` (API/ملف/Copilot، `COPILOT_URL`) ← `_plan_block` (QProgressBar لكل قسم، «أعد صياغة هذا المحور») ← `_research_notes_block` ← `_preview_block` («دمج في البحث»، «دمج الكل»، «أعد صياغة النتيجة»)؛ `_write_ready`, `_write_despite`, `_rewrite_axis`, `_export_prompt`, `_import_reply(from_file, text)`, `_fx_dialog`, `_rp_progress_cb`/`_rp_tick`؛ المعرّفات في المنتقي `S:<مفتاح>` و`C2`. `OPEN_EXTERNAL`, `AUTO_CONCLUSION`. |
- الاختبار: `python -W ignore -m unittest test_research_pipeline -v` (34). نسخة احتياطية: `قديم\backup-research-20261020\`. `case_research.py` القديم باقٍ للقضايا القديمة واختباراتها (ونافذة المسار القديمة `CaseTrackDialog._do_research`).

## 🧱 التقرير المركَّب بالكود v3 (2026-10-20) — صحيح مهما كان النموذج ضعيفاً
| ملف | الدور |
|---|---|
| `case_facts.py` | نموذج الحقائق الصارم `data['facts3']` + `03_حقائق/الحقائق.json`: `parties` (الجنس بدليل نصي)، `contracts` (عقد حقيقي فقط) + `service_orders`، `invoices` (+`components` للغرامة، `stated_remaining`)، `payments`، `statement_totals` (لا تُجمع)، `claim`، `minutes` (`minutes_facts`)، `defenses`. `corpus` (المقدّم من وجه الحافظة، رقم المستند من «مستند (N)»)، `cite`، `scan` (قارئ الكود للجداول/صفحات الفواتير/الأجهزة/طلبات الخدمة)، `extract_prompt`/`verify_model` (اقتباس حرفي + كل رقم/تاريخ في صفحته)، `merge` (الجدول مرجع)، `normalize_contracts` (الخط ليس عقداً)، `covered`، `build(base, data, ask, force)`. |
| `calc.py` | + `ledger(facts)`: لكل خط/عقد (فواتير، غرامات، أصل، مسدد للأصل/للغرامة، متبقٍ للأصل/للغرامة) + الإجمالي + `checks` (كل فرق ولو فلساً مع المطالبة وكشف المدعية). |
| `report_playbooks.py` | `case_type`, `PLAYBOOKS` (اتصالات/مقاولة_توريد/شراكة/عام)، `classify`, `mission_axes` (محور واحد لكل نوع سؤال، عنوان 3–8 كلمات)، `ALLOWED` (أنواع الحقائق لكل محور — الجزء 8). |
| `report_compose.py` | `Ctx` (حقائق+دفتر+قيم الخانات+المراجع لأول ذكر)، `Party` (الجنس النحوي)، `slot_specs`/`slot_keys`/`slots_prompt`/`fill`/`check_slot`/`draft_slots`/`fallback` (النموذج يملأ خانات قصيرة بعبارات مرجعية فقط)، `axis_*` و`compose_axes`، `subject_text`، `procedures_text`، `conclusion_paragraphs`، `compose`، `full_text`، `word_count`. |
| `report_audit.py` | `audit(rep, ctx)` الفحوص (أ)–(ك)، `axes_of_errors`، `Allowed`. |
| `report_v3.py` | `run` (يوجّه إليه `research_pipeline.run` عند `ENABLED`)، `produce` (إعادة مرة بقائمة الأخطاء ثم احتياطي الكود، حدّ 900 كلمة)، `store` (research2 بمحور=قسم `:v3` + الموضوع + الإجراءات + الملاحظات + «كُتب بواسطة» + ذاكرة القضية)، `store_conclusion` (من `conclusion_pipeline.generate`)، `export_prompt`/`import_reply` (ملف/Copilot = الخانات)، `audit_line` (الخط الأحمر في `qt_case_page._research_notes_block`). |
| `gemini_config.py` | + `list_models`, `rank_pro`, `pro_candidates`, `pro_setting`/`save_pro_setting` (`[gemini_models] pro`)، `last_model_used`, `describe_model`, `_PRO_BLOCKED`؛ `_generate_on_client(models=…)`. |
| `ai_providers.py` / `case_research.py` | `PRO_TASKS` ← `GeminiProvider.tier='pro'`, `last_model`؛ `default_ask(task='research')` ← Gemini وحده. `qt_settings_page._gemini_model_row` (اختيار النموذج + تحديث القائمة). |
| `qt_context_menu.styled_menu` | قائمة بنمط صريح (لا QMenu عارية: تظهر صندوقاً أسود داخل صفحة بنمط شفاف) — زر 🔄 «إعادة عمل OCR» ومقدّم الحافظة في `qt_documents_panel`؛ `DocumentsDialog._redo`/`_redo_finished`/`_alert` (رسالة عربية، لا خروج صامت)؛ `case_documents.reconvert` (تقدّم الصفحات + الفشل حالة). |
- الاختبار: `python -W ignore -m unittest test_report_v3 -v` (46؛ الكل 689). تجربة القضية: `تجارب/A2263973_20261020/`. نسخة احتياطية: `قديم\backup-report-v3-20261020\`.

## 🔑 مفاتيح الخبير الشخصية والتشفير (2026-10-21)
| ملف | وظيفته |
|---|---|
| `secret_store.py` (جديد) | DPAPI (`CryptProtectData`/`CryptUnprotectData` عبر ctypes، نطاق المستخدم) بصيغة `dpapi:<base64>`: `protect`/`unprotect`، `write_key`/`read_key` (ملف JSON صغير؛ يرحّل النص الصريح القديم ذاتياً ويستبدله)، `protect_rows`/`unprotect_rows` (نسخة القسم المحلية)، `atomic_write_json`. |
| `gemini_config.py` (إضافات) | `save/load_openai_key` (`openai_key.json`)، المفاتيح الأربعة عبر `secret_store`، `explain_key_failure`، `note_personal_failure`/`pop_personal_failures`، `redact`/`_SECRET_RE` (مستعملة في `short_error` و`_log`)، `mask_key` 4+4 (<16 = لا شيء). |
| `ai_providers.py` (إضافات) | `OpenAIOwnProvider` + `rank_openai_models` (اختيار أقوى نموذج من `/models` بلا اسم ثابت)، `OPENAI_NAME='chatgpt'`، `_is_openai_row`، `key_source(which)` + `KEY_SOURCE_TEXT`، `provider_label` («(مفتاحك)»/«(مفتاح القسم)»)، `test_own_gemini/openai/ocrspace`، `pop_personal_failures`؛ `build_chain` يحجب مفتاح القسم عند وجود الشخصي؛ `run_chain` يسجّل فشل الشخصي ويلحقه برسالة الفشل. |
| `ocr_vision.py` | المفتاح مشفّر، يُرسل بترويسة `X-Goog-Api-Key`، وفشله يُسجَّل كفشل شخصي. `ocr_space.py`: فشل المفتاح الخاص يُسجَّل كذلك. |
| `provider_sync.py` | `_save_cache`/`_load_cache` مشفّران فعلاً (ترحيل تلقائي للنص الصريح)، `migrate_local_secrets()` عند `start_refresh`. |
| `doc_router.py` | `best_engine_source()` ← 'own'/'shared'/''. |
| `qt_settings_page.py` | «الإعدادات العامة»: قسم «قراءة المستندات (OCR)» (Vision، OCR.space) وقسم «مفاتيح الذكاء الاصطناعي» (Gemini، ChatGPT) عبر `KEY_CARDS` + `_build_key_card/_save_key/_test_key/_open_url`. الأدمن يبقى له «التشخيص ← المزودات» لمفاتيح القسم. |
| `qt_case_track.py` | `_offer_provider_choice` يعرض تحذير فشل المفتاح الشخصي. `case_research.default_ask` يسجّل المزوّد مع نوع المفتاح. |
| `secret_audit.py` | يغطي `openai_key.json` + `find_key_leaks_in_logs`. |
| `test_key_priority.py` | 47 اختباراً: الأولوية، الترحيل/التشفير، عدم التسرّب، نماذج OpenAI، بطاقات الواجهة والروابط. |
- مسارات التخزين: `%LOCALAPPDATA%\ExpertApp\experts\<الخبير>\{gemini,openai,vision,ocr}_key.json` (مشفّرة، لكل مستخدم) · `ai_providers_cache.json` (مشفّر، نسخة القسم) · مفاتيح القسم الأصلية في Supabase `app_version` id=2 (بلا تشفير، بقرار المالك). DPAPI مرتبط بحساب ويندوز والجهاز: نقل الملف لجهاز آخر يتطلب إعادة إدخال المفتاح.

## 🛑 فشل المفتاح الشخصي = توقف وخيارات (2026-10-21)
- `ai_providers.py`: `PersonalKeyFailure` (kind, cause, alt, section)، `personal_failure(p, e)`، `pop_key_failure`، `set_key_choice/get_key_choice/clear_key_choice/reset_key_state`، `_is_groq` (استبعاد Groq)، `provider_label` يذكر الاختيار؛ `build_chain` يطبّق الاختيار (`alt` يستبعد الفاشل كله، `section` يفتح مفتاح القسم له).
- `gemini_config.py`: `failure_cause` (invalid|quota|rate|network|other)، `CAUSE_TEXT`؛ `generate_from_pdf` يعيد رفع `PersonalKeyFailure`. `doc_router.py`: `gemini_engine`/`read_numbers_pdf` لا يسقطان لمحرّك آخر.
- `qt_case_track.py`: `_last_job` في `_run_bg`، `_ask_key_failure` (أزرار: أعد المحاولة / ChatGPT (مفتاحك) / مفتاح القسم بتأكيد / إلغاء)، `_choice_active` يُمحى في `_on_done`.
- `case_facts.minutes_facts` (`complete`, `missing_count`) + `report_compose.procedures_text/axis_defense`: بوابة الاكتمال للإجراءات. الاختبارات: `test_key_failure.py` و`ProceduresGateTests` في `test_report_v3.py`.

## 🗂️ البنية المختصرة لمجلد القضية + خط البداية التلقائي (2026-10-21) — يحلّ محل «مجلد القضية هو الأصل» أعلاه
```
<رقم الخبرة>/  مستندات_النظام/  حوافظ/  مذكرات/  أخرى/  markdown/<نفس البنية>  الملخص.md  التقرير/
               _نظام/ (مخفي): case.json(.bak) manifest.json 03_حقائق/ 04_تقرير/(مسودات) مصادر/ سجلات/ إخطارات/
                              فهرس_المستندات.md العقود.md 01_اصول/ 02_markdown/ (قديم، قراءة فقط)
```
| ملف | الدور |
|---|---|
| `case_layout.py` (جديد) | الثوابت (`SYS, SYSDOCS, PORTF, MEMOS, OTHER, CASE_FILE, MANIFEST, WORK_DIR, FACTS_DIR, LOGS_DIR, REPORT_DIR, SUMMARY`)، `ensure` (+إخفاء `_نظام`)، `needs_migration`/`migrate` (نقل بـ`safe_move` بعد sha1، سجل `_نظام/سجلات/ترحيل_البنية.log/.json`، نسخة `قبل_الترحيل/`، `rewrite_refs`، حذف المجلدات الفارغة فقط)، `relocate(base, data, old, new, man)` (نقل أصل + مشتقه + manifest + مراجع case.json). |
| `case_folder.py` | `kind_of(rel)` (النوع من المجلد والاسم)، `KIND_LABELS`، `minute_name`/`minute_file_name` (الرقم من نص المحضر)، `has_kind`، `fetch_from_system(kinds=)` بالأسماء المعتمدة، `add_original` يقبل نوعاً (`_kind_target`) والمجهول ← أخرى، `convert_guarded`/`_with_watchdog`/`ConversionLoop`/`RETRY_BATCHES=(5,2)`/`STALL_SECONDS`، `sync_case_folder(on_file=)`، `latest_md(base, kind)`. |
| `case_startup.py` (جديد) | `STEPS` التسع، `run(base, data, cookies, ask, contract_ask, convert, stop, on_update, fetch, referral_ask)`، `state`/`live`/`counter_text`/`complete`، `originals`، `loose_files`، `_register_sources`، يسجّل مهمتي «الفرز» و«العقد» = research. |
| `case_sort.py` (جديد) | `build_prompt`/`excerpt`/`split_pages`/`part_text`، `verify_part` (حرفية التاريخ/الصفة/النوع، رقم المحضر من نصه)، `role_label` (الجنس والترتيب)، `decide`، `is_canonical`، `pending`، `run`، `apply`، `questions`، `answer`. السجل في manifest `e['sort']` و`data['sort']`. |
| `case_main_contract.py` (جديد) | `portfolios` (الأقدم أولاً، يشمل أجزاء الحوافظ في المختلط)، `find` (ببصمة)، `verify`، `republish`، `where`، `short`؛ `data['main_contract']`. |
| `case_summary.py` (جديد) | `render`/`write`/`write_quiet` (من `cw.write_case_json`)، `documents`، `sources`. |
| `case_autowrite.py` (جديد) | `run(base, data, write_subject, write_procedures)`، `accept_newer`، `line`، `NOTES`، `NEWER`؛ `data['autowrite']`. |
| `loop_guard.py` (جديد) | `detect(text, pages)`/`check` + `LoopDetected`. `doc_router`: `set_batch_override`/`batch_override`، `start_watch`/`stop_watch`/`check_stall`/`Stalled`، `PROGRESS_LISTENERS`، فحص الحلقة لكل دفعة في `gemini_engine`. |
| `qt_startup_panel.py` (جديد) | `StartupPanel` (خطوات يميناً + جدول المستندات + أحمر «إعادة»/«تحديد»)، `SortAnswerDialog`، `step_rows`/`doc_rows`. |
| `qt_case_page.py` | `STARTUP_VIEW`، `_retry_conversion`، `_answer_sort`، `_autowrite_block`/`_accept_newer`. `qt_case_track.sync_folder` ← `case_startup.run` + `case_autowrite.run` (`AUTO_WRITE`). |
| `qt_expert_reports.py` | `open_case_folder` (`STARTFILE`) — أيقونة المجلد تفتح المستكشف فقط. |
| `expert_settings.py` | `case_minutes_dir` = مستندات_النظام، `minute_path`، `notice_path`. |
- الاختبار: `python -W ignore -m unittest test_case_layout -v` (29). نسخة احتياطية: `قديم\backup-case-layout-20261021\`.

## 🧩 الإجراءات: مسار كتابة واحد (2026-10-21)
- `case_procedures.py`: `minutes_gate` (بوابة الاكتمال + `note`)، `evidence` (إعلان/مناقشة من نص المحاضر، يُحفظ في `procedures.evidence`)، `proven_facts` (حقائق مثبتة: attended/notified/discussed/count/complete)، `attendance_clause(result, complete, reason, notified)` (بلا عدد جلسات؛ «عدة جلسات» ثابتة في القالب)، `_discussed_clause`، **`compose(data, facts=None)` → (نص، ملاحظات)** و`compose_text`. القالب: «عدة جلسات {attendance}».
- `report_compose.procedures_text` ← `cp.compose`؛ `case_facts.minutes_facts` ← `cp.proven_facts` (+ ما قُدّم والطلبات والتواريخ). لا نسخة ثانية للمنطق.
- الاختبارات: `UnifiedGateTests` في `test_case_procedures.py` و`ProceduresGateTests` في `test_report_v3.py`.
