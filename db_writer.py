# -*- coding: utf-8 -*-
"""
db_writer.py — تفكيك الأرقام + الكتابة الفعلية بجدول [main] في ExpretDB.MDB

الأعمدة الحقيقية (Name) مقابل ما تعرضه واجهة Access (Caption) مختلفة —
مكتشفة بالتجربة المباشرة (انظر الجلسة اللي اكتشفنا فيها إن الجدول
الصحيح اسمه "main" مو "جدول الاسماء"). نستخدم دائمًا الأسماء
الحقيقية بالإنجليزي بجمل SQL.
"""
import pyodbc
import re
import datetime
from main1_config import load_db_path


def get_connection():
    """يفتح اتصال جديد بقاعدة البيانات — المسار يُقرأ من الإعدادات دائمًا"""
    db_path = load_db_path()
    return pyodbc.connect(
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=" + db_path + ";"
    )


# ============================================================
# تفكيك رقم الخبرة: A2261234 -> no1=1234, no2='A', no3=2026
# ============================================================
def parse_expertise_number(raw):
    """
    يفكك رقم الخبرة من صيغة النظام الجديد: حرف + رمز سنة (3 أرقام) +
    رقم القضية (4 أرقام)، مثال: A2261234
      - الحرف الأول: no2  ('A')
      - رمز السنة (3 أرقام، مثل '226'): نعيد بناء السنة الكاملة
        بإدخال '0' بعد أول رقم -> '226' -> '2' + '0' + '26' = '2026'
      - آخر 4 أرقام: no1 (رقم القضية، مع الأصفار البادئة كما هي)

    يرجع dict: {'no1': str, 'no2': str, 'no3': int, 'ref': str}
    يرمي ValueError لو الصيغة غير متوقعة (طول غير مطابق).
    """
    raw = (raw or '').strip().upper()
    m = re.match(r'^([A-Z])(\d{3})(\d{4})$', raw)
    if not m:
        raise ValueError(
            f"صيغة رقم الخبرة غير متوقعة: {raw!r} — المتوقع حرف+3 أرقام سنة+4 أرقام قضية (مثل A2261234)"
        )
    letter, year_code, case_digits = m.groups()

    year_full = year_code[0] + "0" + year_code[1:]  # "226" -> "2026"

    no1 = case_digits  # نحتفظ بالأصفار البادئة كما هي (حسب طلبك)
    no2 = letter
    no3 = int(year_full)
    ref = f"{no1}/{no2}/{no3}"

    return {'no1': no1, 'no2': no2, 'no3': no3, 'ref': ref}


# ============================================================
# تفكيك رقم الدعوى المستخرج بالذكاء الاصطناعي:
# "3031/2026 تجاري كلي/20" -> c_year, c_no, c_lett, c_last_no
# ============================================================
def parse_court_case_number(court_case_number):
    """
    الصيغة الفعلية المكتشفة بالتجربة: تسلسلي/سنة نوع_دعوى/رقم_دائرة
    مثال: "6143/2025 ت.م.ك.ح/16"
      -> c_no=6143, c_year=2025, c_lett="ت.م.ك.ح", c_last_no=16

    "رقم المحكمة" المعروض بجدول main فعليًا = c_year/c_no/c_lett/c_last_no
    مجمّعين بفواصل '/'.

    يرجع dict فاضي القيم (بدون رمي خطأ) لو الصيغة غير متوقعة — تُترك
    الحقول فاضية للتعديل اليدوي بدل ما يوقف البرنامج.
    """
    result = {'c_no': '', 'c_year': '', 'c_lett': '', 'c_last_no': ''}
    if not court_case_number:
        return result

    raw = court_case_number.strip()

    # الصيغة الأساسية: تسلسلي/سنة نوع_دعوى/رقم_دائرة (مع مسافات مرنة)
    m = re.match(
        r'^\s*(\d+)\s*/\s*(\d{4})\s*(.*?)\s*/\s*(\d+)\s*$',
        raw
    )
    if m:
        c_no, c_year, c_lett, c_last_no = m.groups()
        result.update({
            'c_no': c_no, 'c_year': c_year,
            'c_lett': c_lett.strip(), 'c_last_no': c_last_no,
        })
        return result

    # صيغة احتياطية: بدون شرطة أخيرة (تسلسلي/سنة نوع_دعوى بس، بدون رقم دائرة)
    m2 = re.match(r'^\s*(\d+)\s*/\s*(\d{4})\s+(.+?)\s*$', raw)
    if m2:
        c_no, c_year, c_lett = m2.groups()
        result.update({'c_no': c_no, 'c_year': c_year, 'c_lett': c_lett.strip()})
        return result

    return result


def build_court_number_display(c_year, c_no, c_lett, c_last_no):
    """يبني نص 'رقم المحكمة' المعروض من الأجزاء الأربعة (للمراجعة بالواجهة فقط)"""
    return f"{c_year}/{c_no}/{c_lett}/{c_last_no}"


def build_experts_dash_string(names):
    """
    يبني صيغة عمود 'ex name' اللي تحتفظ بشرطات فاضية للأعضاء غير
    الموجودين، مثال: خبير واحد فقط -> "اسم -  -  -  - "
    """
    names = [n.strip() for n in names if n and n.strip()]
    slots = (names + [''] * 5)[:5]
    return ' - '.join(slots) if any(slots[1:]) else f"{slots[0]} -  -  -  - "


def today_ddmmyyyy():
    return datetime.date.today().strftime('%d/%m/%Y')


# ============================================================
# الكتابة الفعلية بجدول main
# ============================================================
def get_expert_names():
    """
    يجيب كل الأسماء المسجلة بجدول 'اسم الخبير' (جدول lookup بعمود
    واحد) — يُستخدم لتعبئة قائمة منسدلة بدل الكتابة اليدوية الحرة،
    لمنع أي خطأ إملائي أو اسم غير مطابق بقاعدة البيانات الرئيسية.
    يرجع قائمة فاضية بصمت لو تعذر الاتصال (لا يوقف الواجهة).
    """
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM [اسم الخبير]")
        col = cursor.description[0][0]
        names = sorted({
            (row[0] or '').strip()
            for row in cursor.fetchall()
            if row[0] and str(row[0]).strip()
        })
        return names
    except Exception:
        return []
    finally:
        if conn:
            conn.close()


def get_expert_specialty(expert_name):
    """
    آخر 'رمز تخصص' مسجّل لاسم الخبير بجدول main (قاعدة القسم) — يُستخدم
    لاختيار التخصص تلقائياً بصفحة 'إضافة قضية' (بدل الاختيار الافتراضي).

    يرجّع نص العمود 'spe' (مثل 'كهرباء 15' / 'كمبيوتر 24') أو نص فاضي لو:
    الاسم فاضي، أو ما فيه تخصص مسجّل لهذا الخبير، أو تعذّر الاتصال
    (best-effort — لا يوقف الواجهة).
    """
    name = (expert_name or '').strip()
    if not name:
        return ''
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cols = ['expr name1', 'expr name2', 'expr name3', 'expr name4', 'expr name5']
        where = ' OR '.join('[%s] = ?' % c for c in cols)
        cursor.execute(
            f"SELECT [spe] FROM [main] WHERE ({where}) AND [spe] IS NOT NULL AND [spe] <> ''",
            [name] * len(cols))
        rows = [str(r[0]).strip() for r in cursor.fetchall() if r[0] and str(r[0]).strip()]
        if not rows:
            return ''
        # تخصص الخبير عادةً ثابت — ناخذ الأكثر تكراراً
        return max(set(rows), key=rows.count)
    except Exception:
        return ''
    finally:
        if conn:
            conn.close()


def get_department_week_sessions(date_from, date_to):
    """
    كل جلسات جدول [الاحداث] ضمن فترة معيّنة (كائنات datetime.date أو
    datetime)، مربوطة بمعلومات القضية/الخبراء من جدول [main] عبر
    [ref] — هذا هو المصدر الفعلي لـ"كشف جلسات القسم" (بديل عن أي نظام
    خارجي: البيانات موجودة أصلاً بقاعدة القسم المحلية لأنها نفس
    القاعدة اللي تُدخل فيها القضايا وجلساتها).

    يرجع قائمة dict: {date, time, type, ref, name_c, name_p, experts:[...]}
    مرتبة بالتاريخ ثم الوقت. experts = كل أسماء الخبراء المسندين لهذي
    القضية (expr name1..5 غير الفاضية).
    """
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT e.[nex mt d], e.[nm time], e.[nex mt t], e.[ref],
                   m.[name c], m.[name p],
                   m.[expr name1], m.[expr name2], m.[expr name3],
                   m.[expr name4], m.[expr name5]
            FROM [الاحداث] e INNER JOIN [main] m ON e.[ref] = m.[ref]
            WHERE e.[nex mt d] BETWEEN ? AND ?
            ORDER BY e.[nex mt d], e.[nm time]
        """, date_from, date_to)

        results = []
        for row in cursor.fetchall():
            event_date, event_time, event_type, ref, name_c, name_p, *expr_names = row
            experts = [n.strip() for n in expr_names if n and str(n).strip()]
            results.append({
                'date': event_date,
                'time': event_time,
                'type': (event_type or '').strip(),
                'ref': ref,
                'name_c': (name_c or '').strip(),
                'name_p': (name_p or '').strip(),
                'experts': experts,
            })
        return results
    except Exception:
        return []
    finally:
        if conn:
            conn.close()


def insert_event_record(caso_no, date_raw, time_str, type_label):
    """
    يضيف صف "جلسة قادمة" جديد بجدول [الاحداث] — بالتوازي مع تسجيلها
    بنظام الخبراء الرسمي وتقويم آيفون. Best-effort بالكامل: أي عائق
    (تعذّر الاتصال بالقاعدة، القضية غير موجودة بجدول main، صيغة رقم
    خبرة غير متوقعة...) يُتجاهل بصمت — هذا الجدول إضافي وليس مصدر
    الحقيقة الأساسي (نظام الخبراء هو الأساس)، فلا يستاهل إزعاج
    المستخدم أو إيقاف أي شي لو فشل.

    الأعمدة الحقيقية بجدول الاحداث (مكتشفة بالفحص المباشر):
      ref       — نفس صيغة ref بجدول main ("no1/no2/no3"، مثال 1234/A/2026)
      nex mt no — رقم تسلسلي للحدث ضمن نفس القضية (نحسبه: أكبر رقم
                  موجود لنفس ref + 1)
      nex mt d  — تاريخ الجلسة (datetime بدون وقت)
      nm time   — وقت الجلسة (Access يخزّن التوقيت كـdatetime بتاريخ
                  أساس ثابت 1899-12-30 + الساعة/الدقيقة الفعليين)
      nex mt t  — نص نوع الجلسة بالعربي (مثل "مناقشة"، "جلسة محكمة")

    caso_no: رقم الخبرة بصيغة النظام (مثال A2261234).
    date_raw: 'YYYY/MM/DD'. time_str: 'HH:MM' (أو 'HH:MM:SS').
    type_label: نص نوع الجلسة بالعربي كما يُخزَّن بعمود nex mt t.

    يرجع (True, None) عند النجاح الفعلي، أو (False, سبب) عند أي تخطي
    — القيمة المرجعة للتشخيص فقط، المستدعي يتجاهلها بأمان.
    """
    conn = None
    try:
        try:
            parsed = parse_expertise_number(caso_no)
        except Exception:
            return False, "تعذر تفكيك رقم الخبرة"

        # القضايا القديمة بجدول main مسجلة بدون أصفار بادئة بـno1 (مثال:
        # "106/A/2025")، أما القضايا المضافة حديثاً عبر أداة الإضافة
        # الجديدة فتُسجَّل بالأصفار البادئة كاملة (مثال: "0106/A/2025").
        # نجرب الصيغتين ونستخدم أيهما موجود فعلياً بجدول main.
        no1_padded = parsed['no1']
        try:
            no1_stripped = str(int(no1_padded))
        except ValueError:
            no1_stripped = no1_padded

        candidates = [f"{no1_padded}/{parsed['no2']}/{parsed['no3']}"]
        if no1_stripped != no1_padded:
            candidates.append(f"{no1_stripped}/{parsed['no2']}/{parsed['no3']}")

        conn = get_connection()
        cursor = conn.cursor()

        ref = None
        for cand in candidates:
            cursor.execute("SELECT COUNT(*) FROM [main] WHERE [ref] = ?", cand)
            if cursor.fetchone()[0]:
                ref = cand
                break
        if ref is None:
            return False, "القضية غير موجودة بجدول main"

        cursor.execute("SELECT MAX([nex mt no]) FROM [الاحداث] WHERE [ref] = ?", ref)
        row = cursor.fetchone()
        next_no = (row[0] or 0) + 1

        y, m, d = [int(x) for x in date_raw.strip().split('/')]
        event_date = datetime.datetime(y, m, d)

        hh, mm = [int(x) for x in time_str.strip().split(':')[:2]]
        event_time = datetime.datetime(1899, 12, 30, hh, mm)

        cursor.execute(
            "INSERT INTO [الاحداث] ([nex mt no], [nex mt d], [nm time], [ref], [nex mt t]) "
            "VALUES (?, ?, ?, ?, ?)",
            next_no, event_date, event_time, ref, type_label
        )
        conn.commit()
        return True, None
    except Exception as e:
        return False, str(e)
    finally:
        if conn:
            conn.close()


def insert_case_record(fields):
    """
    fields: dict فيه كل القيم النهائية (بعد المراجعة والتعديل اليدوي
    بالواجهة). المفاتيح المتوقعة تطابق أسماء أعمدة main الحقيقية:
    ref, no1, no2, no3, name_c, name_p, reg_date_r, ex_name,
    c_name, c_no, c_year, c_lett, c_last_no, court_no, comm, type,
    boss_est, expr_name1..5, spe, courtdate

    كل حقل غير موجود بـfields يُترك فاضيًا (None) بقاعدة البيانات.
    يرجع (True, None) عند النجاح، أو (False, رسالة_الخطأ) عند الفشل.
    """
    # تحويل من مفاتيح بايثون (بدون مسافات) لأسماء الأعمدة الحقيقية
    column_map = {
        'ref': 'ref', 'no1': 'no1', 'no2': 'no2', 'no3': 'no3',
        'name_c': 'name c', 'name_p': 'name p',
        'reg_date_r': 'reg_date r', 'ex_name': 'ex name',
        'c_name': 'c name', 'c_no': 'c no', 'c_year': 'c year',
        'c_lett': 'c lett', 'c_last_no': 'c last no',
        'section_no': 'section no',
        'court_no': 'court no', 'comm': 'comm', 'type': 'type',
        'boss_est': 'boss est',
        'expr_name1': 'expr name1', 'expr_name2': 'expr name2',
        'expr_name3': 'expr name3', 'expr_name4': 'expr name4',
        'expr_name5': 'expr name5',
        'spe': 'spe', 'courtdate': 'courtdate',
    }

    present = {k: v for k, v in fields.items() if k in column_map and v not in (None, '')}
    if not present:
        return False, "لا توجد بيانات للحفظ"

    columns_sql = ", ".join(f"[{column_map[k]}]" for k in present)
    placeholders = ", ".join("?" for _ in present)
    values = list(present.values())

    sql = f"INSERT INTO [main] ({columns_sql}) VALUES ({placeholders})"

    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(sql, values)
        conn.commit()
        return True, None
    except Exception as e:
        return False, str(e)
    finally:
        if conn:
            conn.close()
