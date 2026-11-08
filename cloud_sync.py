# ===== cloud_sync.py — مزامنة قاعدة الخبير المحلية مع قاعدة رئيس القسم =====
"""
يربط قاعدة SQLite المحلية (case_db.py) بقاعدة Supabase السحابية.

آلية العمل (حسب الاتفاق):
  1. عند فتح البرنامج، فحص خفيف واحد فقط: "هل هذا الخبير مفعّل
     للمزامنة؟" (is_sync_enabled). لو لا، ما يصير أي رفع إطلاقاً.
  2. لو مفعّل: نجيب كل الصفوف اللي needs_sync='1' من القاعدة
     المحلية (case_db.get_pending_sync_rows) ونرفعها دفعة وحدة
     (upsert) للسحابة، وبعد النجاح نصفّر needs_sync محلياً
     (case_db.mark_synced).

رئيس القسم هو اللي يفعّل/يعطّل الخبير من جهته (عبر تطبيقه لاحقاً،
أو مؤقتاً يدوياً من SQL Editor بـSupabase) — ما فيه أي تفعيل ذاتي
من طرف الخبير نفسه.
"""
import requests
import json

from config import SUPABASE_URL, SUPABASE_KEY
import case_db

# أعمدة نرفعها للسحابة فقط (نسخة مصغّرة — لا نرفع plaintiffs/defendants/
# mission_text وغيرها من التفاصيل الحساسة/الثقيلة، فقط ما يحتاجه رئيس
# القسم للمتابعة والإحصائيات)
CLOUD_COLUMNS = [
    'caso_no', 'autocase_no', 'expert_name', 'case_type', 'title',
    'received_date', 'court_case_number', 'status', 'status_updated_at',
    'is_committee', 'committee_members', 'updated_at',
]

_HEADERS = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json',
}


def is_sync_enabled(expert_name, timeout=5):
    """
    فحص خفيف واحد: هل هذا الخبير مفعّل للمزامنة من طرف رئيس القسم؟
    يُستدعى مرة وحدة بس عند فتح البرنامج (حسب الاتفاق). أي خطأ
    اتصال (لا إنترنت، السيرفر واقع...) يُعامَل كـ False بصمت —
    البرنامج يشتغل عادي محلي بدون أي إزعاج للمستخدم.
    """
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/expert_sync_status",
            headers=_HEADERS,
            params={'expert_name': f'eq.{expert_name}', 'select': 'sync_enabled'},
            timeout=timeout,
        )
        if r.status_code != 200:
            return False
        rows = r.json()
        return bool(rows and rows[0].get('sync_enabled'))
    except Exception as e:
        print(f"is_sync_enabled ERROR: {e}")
        return False


def _row_to_cloud_payload(row):
    """يحوّل صف من case_db (dict) لصيغة جاهزة للرفع — يبقي فقط
    الأعمدة المحدودة CLOUD_COLUMNS، ويحوّل committee_members لنص
    JSON (case_db.get_case يرجعها كقائمة بايثون)."""
    payload = {}
    for col in CLOUD_COLUMNS:
        val = row.get(col, '')
        if col == 'committee_members' and isinstance(val, list):
            val = json.dumps(val, ensure_ascii=False)
        payload[col] = val or ''
    return payload


def sync_pending_cases(expert_name, timeout=15):
    """
    يرفع كل القضايا اللي needs_sync='1' بقاعدة الخبير المحلية
    للسحابة (upsert بحسب caso_no)، وبعد نجاح الرفع يصفّر needs_sync
    محلياً. يرجّع (عدد الصفوف المرفوعة, نص خطأ أو None).

    ملاحظة: هذي الدالة لا تتأكد بنفسها من is_sync_enabled — المستدعي
    (نقطة تشغيل البرنامج) هو المسؤول عن الفحص أولاً واستدعاء هذي
    الدالة فقط لو كانت النتيجة True.
    """
    pending = case_db.get_pending_sync_rows()
    if not pending:
        return 0, None

    payloads = [_row_to_cloud_payload(row) for row in pending]

    try:
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/cases",
            headers={**_HEADERS, 'Prefer': 'resolution=merge-duplicates'},
            json=payloads,
            timeout=timeout,
        )
        if r.status_code not in (200, 201):
            return 0, f"فشل الرفع (HTTP {r.status_code}): {r.text[:300]}"

        synced_nos = [row['caso_no'] for row in pending]
        case_db.mark_synced(synced_nos)
        return len(synced_nos), None
    except Exception as e:
        return 0, f"خطأ اتصال: {e}"


def try_sync_on_startup(expert_name):
    """
    نقطة الدخول الوحيدة المطلوب استدعاؤها عند بدء البرنامج (مرة
    وحدة فقط). تسوي الفحص الخفيف، وفقط لو مفعّل تسوي الرفع الفعلي.
    صامتة تماماً بالفشل (لا تُظهر أي رسالة خطأ للمستخدم) — المزامنة
    خلفية بحتة ولا يجب تعطّل تجربة استخدام البرنامج.

    يرجّع dict بسيط للتشخيص (مفيد لو حبينا نطبع حالة بصفحة الإعدادات
    لاحقاً): {'enabled': bool, 'synced': int, 'error': str|None}
    """
    result = {'enabled': False, 'synced': 0, 'error': None}
    try:
        enabled = is_sync_enabled(expert_name)
        result['enabled'] = enabled
        if not enabled:
            return result

        count, err = sync_pending_cases(expert_name)
        result['synced'] = count
        result['error'] = err
    except Exception as e:
        result['error'] = str(e)
    return result
