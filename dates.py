# ===== dates.py — الدالة الموحّدة لكل تواريخ النظام =====
"""
كل تاريخ يدخل النظام (من السيرفر، من كتابة الخبير، من أي مصدر)
يجب أن يمر على normalize_date() أولاً. ترجع دائماً الصيغة الطبيعية
DD/MM/YYYY بدون أي افتراض مسبق لترتيب الأرقام — تتعرف على موضع
السنة (الرقم المكوّن من 4 خانات) لتحديد الترتيب الصحيح تلقائياً.

لا تخلط بين هذه الدالة و to_word_header_date(): الأولى للتطبيع
العام (تُستخدم بكل مكان)، والثانية للعكس الخاص بخلايا جدول الهيدر
فقط (bidi العربي بجداول Word) — ولا تُستخدم إلا بذاك الموضع المحدد.
"""
import re
from datetime import datetime


def normalize_date(date_str):
    """
    تقبل أي تاريخ من أي مصدر بالنظام، بأي فاصل (/ أو -)، وبأي ترتيب،
    وترجعه دائماً بالصيغة الطبيعية DD/MM/YYYY.

      '2026-06-25'          -> '25/06/2026'   (METMONTH / SQL)
      '2026/06/25 10:30:00'  -> '25/06/2026'   (start الجلسات من السيرفر)
      '25/06/2026'          -> '25/06/2026'   (صيغة طبيعية جاهزة)
      '1/4/26'              -> '01/04/2026'   (كتابة يدوية، سنة بخانتين)

    لو فشل بالفهم أو كان التاريخ غير صالح، يرجع النص الأصلي بدون
    تغيير (لا يكسر البرنامج أبداً).
    """
    if not date_str:
        return date_str

    raw = date_str.strip().split(' ')[0]  # نشيل الوقت لو موجود معه
    parts = re.split(r'[/\-]', raw)
    if len(parts) != 3:
        return date_str

    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return date_str

    year_idx = next((i for i, p in enumerate(parts) if len(p) == 4), None)

    if year_idx == 0:
        year, month, day = nums          # YYYY-MM-DD / YYYY/MM/DD
    elif year_idx in (2, None):
        day, month, year = nums          # DD/MM/YYYY (الافتراضي)
        if year < 100:
            year += 2000
    else:
        return date_str

    try:
        datetime(year, month, day)       # تحقق من صلاحية التاريخ
    except ValueError:
        return date_str

    return f"{day:02d}/{month:02d}/{year:04d}"


def to_word_header_date(normalized_date):
    """
    تحوّل تاريخ DD/MM/YYYY إلى YYYY/MM/DD معكوسة.

    ملاحظة (تم التأكد منها فعلياً بتاريخ 25/06/2026 بالتجربة المباشرة):
    خلية جدول الهيدر بمحضر أعمال الخبرة لا تحتاج هذا العكس أبداً —
    تُكتب فيها القيمة الصحيحة DD/MM/YYYY مباشرة (انظر mahdar.py).
    الكود القديم كان يسوي swap بسيط ظنّاً منه أنه تعويض bidi، وكان
    ينجح بالصدفة فقط مع تواريخ المصدر سنة-أول (مثل جلسات السيرفر)
    لأنه فعلياً تحويل صيغة لا عكس bidi حقيقي. الدالة هذه موجودة هنا
    احتياطياً فقط لو ظهر مستقبلاً حقل فعلاً يحتاج عكس bidi حقيقي
    (مثل حقل 'تاريخ صدور الحكم' المعلّق بالقائمة) — يجب التحقق
    بالتجربة الفعلية أولاً قبل استخدامها بأي مكان جديد.
    """
    parts = normalized_date.strip().split('/')
    if len(parts) == 3:
        d, m, y = parts
        return f"{y}/{m}/{d}"
    return normalized_date