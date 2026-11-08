# -*- coding: utf-8 -*-
"""
main1_config.py — إعدادات مسار قاعدة البيانات لبرنامج MAIN1

المسار يُقرأ بثلاث طبقات (بالأولوية):
  1. القيمة المخزّنة بجدول app_config بقاعدة Supabase السحابية — هذي
     القيمة المشتركة الحقيقية. يعدّلها محمد من زر "⚙️ مسار القاعدة"
     بنافذة إضافة قضية (نفس الحقل القديم، بدون أي واجهة أونلاين
     مباشرة)، وأي تعديل ينعكس فورًا على كل الأجهزة بدون توزيع نسخة
     جديدة من البرنامج.
  2. نسخة محلية مخزّنة (main1_settings.json) — تُستخدم فقط كـcache
     تلقائي لآخر قيمة معروفة، تُحدَّث كل مرة تنجح فيها القراءة أو
     الحفظ من السحابة. تُستخدم فقط لو تعذّر الوصول للإنترنت وقت
     التشغيل (لا إنترنت / Supabase واقع مؤقتاً).
  3. DEFAULT_DB_PATH الثابت بالكود — خط دفاع أخير لو الطبقتين فوق
     غير متوفرتين إطلاقاً (أول تشغيل بدون إنترنت ولا كاش محلي سابق).
"""
import os
import json
import requests

from config import SUPABASE_URL, SUPABASE_KEY

SETTINGS_PATH = os.path.join(
    os.environ.get('LOCALAPPDATA', ''), 'ExpertApp', 'main1_settings.json'
)

DEFAULT_DB_PATH = r"\\regex1107p4d075\elecomp\Label\Bin\ExpretDB.MDB"

_CONFIG_KEY = 'mdb_path'

_HEADERS = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json',
}


def _load_local_cache():
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, encoding='utf-8') as f:
                data = json.load(f)
                path = (data.get('db_path') or '').strip()
                if path:
                    return path
    except Exception:
        pass
    return None


def _save_local_cache(path):
    try:
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, 'w', encoding='utf-8') as f:
            json.dump({'db_path': path.strip()}, f, ensure_ascii=False)
    except Exception:
        pass


def _load_cloud_path(timeout=4):
    """يرجع المسار المخزّن بالسحابة، أو None لو تعذّر الاتصال/غير موجود بصمت"""
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/app_config",
            headers=_HEADERS,
            params={'key': f'eq.{_CONFIG_KEY}', 'select': 'value'},
            timeout=timeout,
        )
        if r.status_code != 200:
            return None
        rows = r.json()
        if rows and rows[0].get('value'):
            return rows[0]['value'].strip()
    except Exception:
        pass
    return None


def load_db_path():
    """يرجع مسار القاعدة الفعلي: سحابة أولًا، ثم آخر نسخة محلية معروفة، ثم الافتراضي بالكود"""
    cloud_path = _load_cloud_path()
    if cloud_path:
        _save_local_cache(cloud_path)  # تحديث الكاش المحلي لأي تشغيل لاحق بدون إنترنت
        return cloud_path

    cached = _load_local_cache()
    if cached:
        return cached

    return DEFAULT_DB_PATH


def save_db_path(path):
    """
    يحفظ مسار قاعدة جديد: يرفعه للسحابة أولاً (upsert) عشان ينعكس
    فورًا على كل الأجهزة، ثم يحدّث الكاش المحلي كنسخة احتياطية.
    يرمي استثناء لو فشل الرفع للسحابة — القيمة تُعتبر لم تُحفظ فعليًا
    (بدل حفظها محليًا بصمت وإيهام المستخدم إنها انتشرت لكل الأجهزة).
    """
    path = (path or '').strip()
    if not path:
        raise ValueError("المسار فارغ")

    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/app_config",
        headers={**_HEADERS, 'Prefer': 'resolution=merge-duplicates'},
        json=[{'key': _CONFIG_KEY, 'value': path}],
        timeout=8,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"فشل حفظ المسار بالسحابة (HTTP {r.status_code}): {r.text[:200]}")

    _save_local_cache(path)