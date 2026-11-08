# ===== case_db.py — قاعدة بيانات محلية لتخزين معلومات القضايا المستخرجة =====
"""
قاعدة بيانات SQLite محلية (ملف واحد بـ AppData، نفس مكان credentials.json
وgemini_key.json) — تخزّن كل المعلومات المستخرجة من حكم الإحالة لكل
رقم خبرة، بحيث لا نحتاج نستدعي الذكاء الاصطناعي إلا مرة واحدة فقط
لكل قضية. وجود السجل بالقاعدة هو نفسه إشارة "تم الفحص" — لا حاجة
لعمود حالة منفصل لهذا الغرض (قد تكون بعض الحقول فاضية لو ما فيه حكم
بعد، وهذا طبيعي ويُحدَّث تلقائيًا أول ما يتوفر الحكم).

جاهزة من الآن لمزامنة مستقبلية مع قاعدة رئيس القسم السحابية:
  - status / status_updated_at: حالة القضية (متداولة/محجوزة/منجزة)
  - is_committee / committee_members: هل القضية لجنة أم خبير منفرد
  - needs_sync: علامة "بحاجة رفع للسحابة" — تتفعّل تلقائياً عند أي
    إضافة/تعديل. الرفع الفعلي مسؤول عنه موديول المزامنة (لاحقاً)،
    وفقط لو الخبير "مفعّل" من طرف رئيس القسم (فحص يصير مرة وحدة عند
    فتح البرنامج).

جدول sessions (مضاف): سجل تاريخي لكل جلسة شُوهدت لكل قضية من صفحة
الجلسات الحية — يحل مشكلة اختفاء القضية من قائمة الجلسات بصمت لو
ماتوفرت لها جلسة قادمة (انظر upsert_session / get_no_upcoming_cases).

ملاحظة مهمة: get_no_upcoming_cases() يقتصر على القضايا "المتداولة"
فقط (status='متداولة' بجدول cases، ولنفس الخبير الحالي) — وليس كل
قضية مرّت يوماً على هذا الجهاز. القضايا المحجوزة (status='محجوزة')
تُستبعد عمداً لأنه طبيعي وصحيح ألا تكون لها جلسة قادمة (بانتظار جلسة
الحجز نفسها لا جلسة تالية)، والقضايا المنجزة لا تهمنا هنا إطلاقاً.
"""
import os
import sqlite3
import json
import datetime

DB_PATH = os.path.join(
    os.environ.get('LOCALAPPDATA', ''), 'ExpertApp', 'cases.db'
)

# أعمدة نصية عادية (تُنشأ كـ TEXT ويُرقّى لها الجدول تلقائياً لو ناقصة)
COLUMNS = [
    'caso_no', 'autocase_no', 'expert_name', 'case_type', 'title',
    'received_date', 'plaintiffs', 'defendants', 'court_case_number',
    'judgment_date', 'hearing_date', 'mission_text',
    'requesting_expert_name', 'requesting_expert_type',
    'status', 'status_updated_at', 'is_committee', 'committee_members',
    'needs_sync',
    'judgment_engine',   # JSON: محرّك قراءة حكم الإحالة وأسباب تخطي Gemini (إفصاح بتنبيه أحمر)
    'case_summary',   # ملخص موضوع النزاع بسطر واحد (Gemini من صحيفة الدعوى)
    # ⚠️ referral_date_actual / completion_date_actual / is_redistributed /
    # flow_checked_at: كانت هنا سابقاً كأعمدة بجدول cases المشترك بين
    # كل الخبراء — لكن هذي البيانات نسبية لخبير معيّن (نتيجة تحليل
    # ECS_CASE_FLOW باسم "my_name" وقت الفحص)، فتخزينها بجدول مشترك كان
    # يسبب خلط نتائج بين الخبراء (خبير يشوف نتيجة محسوبة لخبير آخر
    # استخدم نفس الجهاز/القاعدة). انتقلت لجدول منفصل: case_flow_stats
    # (مفتاحه caso_no + expert_name) — أبقيناها بهذي القائمة فقط
    # لتوافق القواعد القديمة (الأعمدة تضل موجودة بالجدول لكن غير
    # مستخدمة بعد الآن، لا تُقرأ ولا تُكتب من أي كود جديد).
    'referral_date_actual', 'completion_date_actual', 'is_redistributed',
    'flow_checked_at',
    'updated_at',
]

STATUS_CHOICES = ('متداولة', 'محجوزة', 'منجزة')


_schema_ready = False


def _connect():
    global _schema_ready
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if not _schema_ready:
        # ضمان وجود الجدول وكل الأعمدة (بما فيها أي عمود جديد أُضيف
        # لاحقاً بـCOLUMNS) بغض النظر عن نقطة الدخول للبرنامج — بعض
        # الشاشات (نسخة Qt) ما تستدعي init_db() صراحة عند البدء.
        _schema_ready = True
        try:
            _ensure_schema(conn)
        except Exception:
            pass
    return conn


def init_db():
    """
    ينشئ الجدول لو غير موجود، ويُرقّي أي قاعدة موجودة فعليًا (من جلسات
    سابقة) بإضافة أي عمود جديد ناقص. يُستدعى صراحة عند بدء البرنامج
    (لو أمكن)، لكن _connect() تضمن استدعاء نفس المنطق تلقائياً أول
    اتصال بأي حال — فما فيه اعتماد إجباري على استدعائها يدوياً.
    """
    conn = _connect()
    conn.commit()
    conn.close()


def _ensure_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cases (
            caso_no TEXT PRIMARY KEY,
            autocase_no TEXT,
            expert_name TEXT,
            case_type TEXT,
            title TEXT,
            received_date TEXT,
            plaintiffs TEXT,
            defendants TEXT,
            court_case_number TEXT,
            judgment_date TEXT,
            hearing_date TEXT,
            mission_text TEXT,
            requesting_expert_name TEXT,
            requesting_expert_type TEXT,
            status TEXT,
            status_updated_at TEXT,
            is_committee TEXT,
            committee_members TEXT,
            needs_sync TEXT,
            updated_at TEXT
        )
    """)

    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(cases)").fetchall()}
    for col in COLUMNS:
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE cases ADD COLUMN {col} TEXT")

    # جدول الجلسات — سجل تاريخي لكل جلسة شُوهدت لكل قضية (من صفحة
    # الجلسات الحية). الهدف الأساسي حالياً: معرفة "آخر جلسة معروفة"
    # لأي قضية حتى لو خرجت من نطاق الجلب الحي (أمس -> +30 يوم)، عشان
    # نكتشف القضايا اللي بدون جلسة قادمة ونبقيها ظاهرة للخبير بدل ما
    # تختفي بصمت. لاحقاً تصلح أساساً لعرض كامل تاريخ جلسات أي قضية.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            caso_no TEXT NOT NULL,
            session_date TEXT NOT NULL,
            session_time TEXT,
            session_type TEXT,
            title TEXT,
            updated_at TEXT,
            UNIQUE(caso_no, session_date, session_time)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_caso ON sessions(caso_no)")

    # جدول إحصائية سجل الحركة — منفصل تمامًا عن جدول cases (المشترك
    # عمداً بين كل الخبراء لبيانات القضية الموضوعية: أطراف/حكم/إلخ).
    # نتائج تحليل ECS_CASE_FLOW (تاريخ آخر إحالة/إنجاز/هل انوزعت لخبير
    # ثاني) نسبية دائمًا لخبير معيّن ("my_name" وقت الفحص) — تخزينها
    # سابقًا كأعمدة على جدول cases المشترك كان يسبب خلطاً خطيراً بين
    # الخبراء: خبير يفتح إحصائيته فيشوف نتيجة محسوبة أصلاً لخبير آخر
    # استخدم نفس الجهاز/القاعدة قبله على نفس القضية. المفتاح هنا
    # (caso_no + expert_name) يفصل تمامًا بين نتائج كل خبير.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS case_flow_stats (
            caso_no TEXT NOT NULL,
            expert_name TEXT NOT NULL,
            referral_date_actual TEXT,
            completion_date_actual TEXT,
            is_redistributed TEXT,
            flow_checked_at TEXT,
            PRIMARY KEY (caso_no, expert_name)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_flow_stats_expert ON case_flow_stats(expert_name)")

    # كاش صفحة "القضايا المحالة" — آخر نتيجة لـget_referred_cases لكل
    # نوع (عادية 130003 / استعانة 130049) لكل خبير. الصفحة تعرضها فورًا
    # عند الفتح بدون انتظار شبكة، وتتحقق بالخلفية هل تغيّرت القائمة.
    # مفتاحه (expert_name + type_id) — نفس مبدأ case_flow_stats: القائمة
    # تخص خبير معيّن، فما تنخلط لو أكثر من خبير استخدم نفس الجهاز.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS referred_cache (
            expert_name TEXT NOT NULL,
            type_id TEXT NOT NULL,
            cases_json TEXT,
            updated_at TEXT,
            PRIMARY KEY (expert_name, type_id)
        )
    """)

    conn.commit()


def has_case(caso_no):
    """تتأكد فقط من وجود رقم الخبرة بالقاعدة، بدون جلب أي بيانات"""
    conn = _connect()
    row = conn.execute(
        "SELECT 1 FROM cases WHERE caso_no = ?", (caso_no.strip().upper(),)
    ).fetchone()
    conn.close()
    return row is not None


def get_case(caso_no):
    """يرجع dict بكل بيانات القضية (plaintiffs/defendants/committee_members
    كقائمة بايثون)، أو None لو غير موجودة"""
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM cases WHERE caso_no = ?", (caso_no.strip().upper(),)
    ).fetchone()
    conn.close()
    if not row:
        return None
    data = dict(row)
    try:
        data['plaintiffs'] = json.loads(data['plaintiffs'] or '[]')
    except Exception:
        data['plaintiffs'] = []
    try:
        data['defendants'] = json.loads(data['defendants'] or '[]')
    except Exception:
        data['defendants'] = []
    try:
        data['committee_members'] = json.loads(data['committee_members'] or '[]')
    except Exception:
        data['committee_members'] = []
    return data


def save_case(caso_no, **fields):
    """
    يحفظ/يحدّث بيانات قضية. يقبل أي مجموعة جزئية من الحقول — مثلاً
    ممكن نحفظ فقط autocase_no وreceived_date أول الأمر (لما ما فيه
    حكم بعد)، ثم نحدّث باقي الحقول لاحقًا أول ما يتوفر الاستخراج،
    بدون فقدان أي قيم سابقة لم تُمرَّر بهذا الاستدعاء.

    plaintiffs/defendants/committee_members تُمرَّر كقائمة بايثون
    عادية (list)، وتُخزَّن داخليًا كـJSON تلقائيًا.

    أي استدعاء لـsave_case (إضافة جديدة أو تعديل) يفعّل needs_sync='1'
    تلقائياً — القضية تصير "بانتظار رفع للسحابة" أول ما يتوفر اتصال
    ويكون الخبير مفعّلاً للمزامنة.
    """
    caso_no = caso_no.strip().upper()
    existing = get_case(caso_no) or {}

    merged = {**existing, **fields}
    merged['caso_no'] = caso_no
    merged['updated_at'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    merged['needs_sync'] = '1'

    if isinstance(merged.get('plaintiffs'), list):
        merged['plaintiffs'] = json.dumps(merged['plaintiffs'], ensure_ascii=False)
    if isinstance(merged.get('defendants'), list):
        merged['defendants'] = json.dumps(merged['defendants'], ensure_ascii=False)
    if isinstance(merged.get('committee_members'), list):
        merged['committee_members'] = json.dumps(merged['committee_members'], ensure_ascii=False)

    values = [merged.get(c, '') or '' for c in COLUMNS]
    placeholders = ', '.join(['?'] * len(COLUMNS))
    update_clause = ', '.join(f"{c}=excluded.{c}" for c in COLUMNS if c != 'caso_no')

    conn = _connect()
    conn.execute(f"""
        INSERT INTO cases ({', '.join(COLUMNS)})
        VALUES ({placeholders})
        ON CONFLICT(caso_no) DO UPDATE SET {update_clause}
    """, values)
    conn.commit()
    conn.close()


def update_status(caso_no, status):
    """
    يحدّث حالة القضية (متداولة/محجوزة/منجزة) فقط لو تغيّرت فعلياً عن
    الحالة الحالية بالقاعدة — تفادياً لكتابة زائدة كل ما تُفتح صفحة
    المتداولة/المحجوزة بدون داعٍ. يفعّل needs_sync ويحدّث
    status_updated_at فقط عند حصول تغيير حقيقي.
    """
    if status not in STATUS_CHOICES:
        raise ValueError(f"status غير معروفة: {status}")

    caso_no = caso_no.strip().upper()
    existing = get_case(caso_no)
    if existing and existing.get('status') == status:
        return False  # ما تغيّر شي، ما نكتب

    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = _connect()
    if existing:
        conn.execute(
            "UPDATE cases SET status=?, status_updated_at=?, needs_sync='1', updated_at=? WHERE caso_no=?",
            (status, now, now, caso_no)
        )
        conn.commit()
        conn.close()
    else:
        conn.close()
        # ما فيه سجل أصلاً بعد — ننشئه عبر save_case العادية
        save_case(caso_no, status=status, status_updated_at=now)
    return True


def set_committee_info(caso_no, is_committee, members=None):
    """
    يسجّل هل القضية لجنة أم خبير منفرد + أسماء الأعضاء (لو لجنة).
    is_committee: True/False. members: قائمة أسماء (تُتجاهل لو is_committee=False).
    """
    save_case(
        caso_no,
        is_committee='1' if is_committee else '0',
        committee_members=(members or []) if is_committee else [],
    )


def count_referred_this_year(expert_name):
    """عدد القضايا المحالة لهذا الخبير من بداية السنة الحالية حتى اليوم،
    بالاعتماد على received_date."""
    year_start = f"{datetime.date.today().year}-01-01"
    conn = _connect()
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM cases WHERE expert_name=? AND received_date>=?",
        (expert_name, year_start)
    ).fetchone()
    conn.close()
    return row['c'] if row else 0


def count_completed(expert_name):
    """عدد القضايا المنجزة لهذا الخبير (كل الأوقات)."""
    conn = _connect()
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM cases WHERE expert_name=? AND status='منجزة'",
        (expert_name,)
    ).fetchone()
    conn.close()
    return row['c'] if row else 0


def get_active_cases(expert_name):
    """يرجّع مجموعة أرقام القضايا 'الحية' حالياً لهذا الخبير (متداولة أو
    محجوزة) بالقاعدة — تُستخدم للمقارنة مع القوائم الحية من الموقع،
    لاكتشاف القضايا التي اختفت من الموقع (أي أصبحت منجزة) تلقائياً."""
    conn = _connect()
    rows = conn.execute(
        "SELECT caso_no FROM cases WHERE expert_name=? AND status IN ('متداولة','محجوزة')",
        (expert_name,)
    ).fetchall()
    conn.close()
    return {r['caso_no'] for r in rows}


def get_active_caso_nos(expert_name):
    """يرجّع مجموعة أرقام القضايا التي حالتها الحالية 'متداولة' أو 'محجوزة'
    لهذا الخبير — تُستخدم لاكتشاف القضايا التي اختفت من القوائم الحية
    (أي أُنجزت) عبر المقارنة مع القائمة الحالية القادمة من الموقع."""
    conn = _connect()
    rows = conn.execute(
        "SELECT caso_no FROM cases WHERE expert_name=? AND status IN ('متداولة','محجوزة')",
        (expert_name,)
    ).fetchall()
    conn.close()
    return {r['caso_no'] for r in rows}


def get_pending_sync_rows():
    """يرجّع كل الصفوف اللي needs_sync='1' — جاهزة للرفع للسحابة."""
    conn = _connect()
    rows = conn.execute("SELECT * FROM cases WHERE needs_sync='1'").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_synced(caso_no_list):
    """يصفّر needs_sync لقائمة من أرقام الخبرة بعد رفعها بنجاح للسحابة."""
    if not caso_no_list:
        return
    conn = _connect()
    nos = [c.strip().upper() for c in caso_no_list]
    placeholders = ', '.join(['?'] * len(nos))
    conn.execute(f"UPDATE cases SET needs_sync='0' WHERE caso_no IN ({placeholders})", nos)
    conn.commit()
    conn.close()


def cleanup_old_cases(years=3):
    """
    يحذف القضايا اللي received_date أقدم من years سنوات من اليوم.
    يُستدعى تلقائياً (مثلاً عند بدء البرنامج) — لا يحتاج تأكيد يدوي
    حسب القرار الحالي. يرجّع عدد الصفوف المحذوفة.
    """
    cutoff = (datetime.date.today() - datetime.timedelta(days=365 * years)).strftime('%Y-%m-%d')
    conn = _connect()
    cur = conn.execute(
        "DELETE FROM cases WHERE received_date != '' AND received_date < ?",
        (cutoff,)
    )
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    return deleted


def delete_case(caso_no):
    """يحذف سجل قضية (احتياطي، نادر الاستخدام)"""
    conn = _connect()
    conn.execute("DELETE FROM cases WHERE caso_no = ?", (caso_no.strip().upper(),))
    conn.commit()
    conn.close()


def _normalize_session_date(d):
    """يوحّد صيغة التاريخ إلى YYYY-MM-DD (يقبل YYYY/MM/DD أو YYYY-MM-DD)."""
    d = (d or '').strip()
    if not d:
        return ''
    d = d.replace('/', '-')
    parts = d.split('-')
    if len(parts) == 3 and len(parts[0]) == 4:
        try:
            return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        except Exception:
            return d
    return d


def upsert_session(caso_no, date, time='', session_type='', title=''):
    """
    يسجّل/يحدّث جلسة واحدة لقضية معيّنة (المفتاح: قضية+تاريخ+وقت).
    يُستدعى في كل مرة تُحمَّل فيها صفحة الجلسات على كل جلسة تُجلب من
    الموقع (حتى لو ماضية) — عشان لو القضية طاحت لاحقاً برّا نطاق
    الجلب الحي، يبقى عندنا آخر جلسة معروفة لها محليًا.
    """
    caso_no = (caso_no or '').strip().upper()
    if not caso_no:
        return
    d = _normalize_session_date(date)
    if not d:
        return
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = _connect()
    conn.execute("""
        INSERT INTO sessions (caso_no, session_date, session_time, session_type, title, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(caso_no, session_date, session_time) DO UPDATE SET
            session_type=excluded.session_type,
            title=excluded.title,
            updated_at=excluded.updated_at
    """, (caso_no, d, time or '', session_type or '', title or '', now))
    conn.commit()
    conn.close()


def get_no_upcoming_cases(expert_name=None):
    """
    يرجّع القضايا "المتداولة فعلياً" (status='متداولة' بجدول cases، ولنفس
    الخبير الحالي لو مُمرَّر expert_name) اللي "آخر جلسة معروفة" لها
    بالماضي — أي ما فيه أي جلسة بتاريخ اليوم أو بعده مسجّلة محليًا.

    ملاحظة: مقصود عمداً استبعاد القضايا المحجوزة (status='محجوزة') —
    طبيعي وصحيح ألا تكون لها جلسة قادمة (بانتظار جلسة الحجز نفسها)،
    وكذلك استبعاد القضايا المنجزة أو أي قضية غير مُتابَعة بجدول cases
    أصلاً (لا تخص القضايا المتداولة الحالية للخبير).

    كل عنصر: {'caso_no', 'session_date', 'session_time', 'session_type',
    'title'} لآخر جلسة معروفة. بمجرد ما تُضاف جلسة قادمة جديدة (تُسجَّل
    عبر upsert_session أول ما تُجلب من الموقع)، تختفي القضية تلقائياً
    من هذي القائمة — بدون أي حاجة لمسح علامة يدوياً.
    """
    today = datetime.date.today().strftime('%Y-%m-%d')
    conn = _connect()

    if expert_name:
        active_rows = conn.execute(
            "SELECT caso_no FROM cases WHERE expert_name=? AND status='متداولة'",
            (expert_name,)
        ).fetchall()
    else:
        active_rows = conn.execute(
            "SELECT caso_no FROM cases WHERE status='متداولة'"
        ).fetchall()
    active_pending = {r['caso_no'] for r in active_rows}

    if not active_pending:
        conn.close()
        return []

    rows = conn.execute("""
        SELECT caso_no, MAX(session_date) AS last_date
        FROM sessions
        GROUP BY caso_no
        HAVING last_date < ?
    """, (today,)).fetchall()

    result = []
    for r in rows:
        if r['caso_no'] not in active_pending:
            continue
        last = conn.execute("""
            SELECT caso_no, session_date, session_time, session_type, title
            FROM sessions WHERE caso_no=? AND session_date=?
            ORDER BY session_time DESC LIMIT 1
        """, (r['caso_no'], r['last_date'])).fetchone()
        if last:
            result.append(dict(last))
    conn.close()
    return result


def get_case_sessions(caso_no):
    """يرجّع كل الجلسات المسجّلة محليًا لقضية معيّنة، من الأقدم للأحدث
    (أساس مستقبلي لعرض تاريخ الجلسات الكامل لأي قضية)."""
    caso_no = (caso_no or '').strip().upper()
    conn = _connect()
    rows = conn.execute("""
        SELECT caso_no, session_date, session_time, session_type, title
        FROM sessions WHERE caso_no=?
        ORDER BY session_date ASC, session_time ASC
    """, (caso_no,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_caso_nos():
    """يرجّع كل أرقام القضايا المخزّنة محلياً (أي خبير) — تُستخدم كأحد
    مصادر 'القضايا المرشّحة' لفحص الإحصائية، جنب سجل الجلسات الحي."""
    conn = _connect()
    rows = conn.execute("SELECT caso_no FROM cases").fetchall()
    conn.close()
    return {r['caso_no'] for r in rows}


def get_all_checked_stats(expert_name):
    """يرجّع كل الصفوف اللي انفحصت إحصائياً (flow_checked_at غير فاضي)
    **لهذا الخبير بالذات فقط** — مع عنوان القضية (من جدول cases
    المشترك، حقل موضوعي بحت لا علاقة له بالخبير)."""
    conn = _connect()
    rows = conn.execute("""
        SELECT s.caso_no AS caso_no, c.title AS title,
               s.referral_date_actual AS referral_date_actual,
               s.completion_date_actual AS completion_date_actual,
               s.is_redistributed AS is_redistributed
        FROM case_flow_stats s
        LEFT JOIN cases c ON c.caso_no = s.caso_no
        WHERE s.expert_name = ?
          AND s.flow_checked_at IS NOT NULL AND s.flow_checked_at != ''
    """, (expert_name,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_case_stats(caso_no, expert_name):
    """يرجّع بيانات إحصائية القضية المخزَّنة محلياً **لهذا الخبير بالذات**
    (تاريخ الإحالة/الإنجاز الفعلي + هل انوزعت لخبير ثاني)، أو None لو ما
    فُحصت هذي القضية بعد لهذا الخبير تحديداً. نفس القضية قد يكون لها
    صفوف منفصلة لخبراء آخرين استخدموا نفس الجهاز — لا تتداخل."""
    conn = _connect()
    row = conn.execute("""
        SELECT referral_date_actual, completion_date_actual,
               is_redistributed, flow_checked_at
        FROM case_flow_stats
        WHERE caso_no = ? AND expert_name = ?
    """, (caso_no.strip().upper(), expert_name)).fetchone()
    conn.close()
    if not row or not row['flow_checked_at']:
        return None
    return {
        'referral_date_actual': row['referral_date_actual'] or '',
        'completion_date_actual': row['completion_date_actual'] or '',
        'is_redistributed': row['is_redistributed'] == '1',
        'flow_checked_at': row['flow_checked_at'] or '',
    }


def save_case_stats(caso_no, expert_name, referral_date_actual='',
                     completion_date_actual='', is_redistributed=False):
    """يحفظ نتيجة فحص سجل الحركة لقضية معيّنة **لهذا الخبير بالذات**
    (تُستدعى مرة لكل قضية لكل خبير، وتُعاد فقط عند طلب 'تحديث' صريح)."""
    conn = _connect()
    conn.execute("""
        INSERT INTO case_flow_stats
            (caso_no, expert_name, referral_date_actual,
             completion_date_actual, is_redistributed, flow_checked_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(caso_no, expert_name) DO UPDATE SET
            referral_date_actual=excluded.referral_date_actual,
            completion_date_actual=excluded.completion_date_actual,
            is_redistributed=excluded.is_redistributed,
            flow_checked_at=excluded.flow_checked_at
    """, (
        caso_no.strip().upper(), expert_name,
        referral_date_actual or '', completion_date_actual or '',
        '1' if is_redistributed else '0',
        datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    ))
    conn.commit()
    conn.close()


def get_referred_cache(expert_name, type_id):
    """يرجّع آخر قائمة قضايا محالة مخزّنة لهذا الخبير ولهذا النوع، أو None
    لو ما انحفظ شي بعد (أول فتح للصفحة على هذا الجهاز)."""
    conn = _connect()
    row = conn.execute(
        "SELECT cases_json FROM referred_cache WHERE expert_name = ? AND type_id = ?",
        (expert_name or '', type_id)).fetchone()
    conn.close()
    if not row or row['cases_json'] is None:
        return None
    try:
        return json.loads(row['cases_json'])
    except Exception:
        return None


def save_referred_cache(expert_name, type_id, cases):
    """يحفظ آخر نتيجة فعلية من السيرفر لقائمة القضايا المحالة (يستبدل السابقة)."""
    conn = _connect()
    conn.execute("""
        INSERT INTO referred_cache (expert_name, type_id, cases_json, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(expert_name, type_id) DO UPDATE SET
            cases_json=excluded.cases_json,
            updated_at=excluded.updated_at
    """, (
        expert_name or '', type_id, json.dumps(cases, ensure_ascii=False),
        datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    ))
    conn.commit()
    conn.close()
