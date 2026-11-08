# ===== icloud_calendar.py — مزامنة مواعيد الجلسات تلقائيًا بتقويم iCloud =====
"""
يضيف موعد الجلسات تلقائيًا للتقويم الافتراضي بالآيفون (عبر iCloud،
بروتوكول CalDAV). كل خبير يربط حسابه الخاص بنفسه من صفحة الإعدادات —
نفس فكرة مفتاح Gemini تمامًا (بيانات محلية، شخصية، لكل مستخدم).

يحتاج Apple ID + App-Specific Password (يُولَّد من appleid.apple.com
→ الأمان → كلمات مرور خاصة بالتطبيق) — مب كلمة مرور الحساب الأصلية.

ملاحظات مهمة (مستخرجة من تجربة فعلية):
  1) دعم iCloud لـCalDAV غير موثّق رسميًا من Apple.
  2) لمنع تكرار المواعيد (وتجديدها بدل تكرارها لو تغيّر تاريخ
     الجلسة)، نستخدم البحث بنطاق تاريخ (date_search) بدل البحث
     بمعرّف فريد (UID) — الأول معيار CalDAV أساسي أكثر ثباتًا.
  3) حساب iCloud الواحد غالبًا فيه أكثر من "تقويم" (الشخصي، تقاويم
     مشتركة، تقاويم نظام كأعياد الميلاد) — وبعضها غير قابل للكتابة
     فعليًا حتى لو ظهر بقائمة principal.calendars(). لذلك لا نفترض
     "أول تقويم بالقائمة" هو الصحيح؛ نجرب الكتابة على كل تقويم
     بالترتيب ونتوقف عند أول واحد ينجح فيه فعليًا (مب فقط يظهر
     بالقائمة). هذا ينطبق على test_connection() كذلك — تتحقق من
     الكتابة الفعلية (تنشئ موعد تجريبي بعيد جدًا بالمستقبل وتحذفه
     فورًا)، مب فقط من نجاح تسجيل الدخول وعرض القوائم.
  3) بيانات الحساب تُحفظ بمجلد خاص بكل خبير على حدة (current_expert.py)
     — مب مجلد عام يتشاركه كل من يستخدم نفس الجهاز، لأن كل خبير له
     حساب iCloud شخصي مختلف.
"""
import os
import json
import datetime
from current_expert import expert_data_dir

_OLD_CONFIG_PATH = os.path.join(
    os.environ.get('LOCALAPPDATA', ''), 'ExpertApp', 'icloud_calendar.json'
)


def _config_path():
    return os.path.join(expert_data_dir(), 'icloud_calendar.json')


def _migrate_if_needed():
    """ينقل (move، لا نسخ) بيانات الحساب من المكان العام القديم لمجلد
    الخبير الحالي مرة واحدة فقط — يختفي من المكان القديم فورًا حتى لا
    يرثه خبير ثاني بالغلط لو الجهاز مشترك"""
    new_path = _config_path()
    if os.path.exists(new_path):
        return
    if not os.path.exists(_OLD_CONFIG_PATH):
        return
    try:
        os.makedirs(os.path.dirname(new_path), exist_ok=True)
        os.replace(_OLD_CONFIG_PATH, new_path)
    except Exception:
        pass


def save_credentials(apple_id, app_password):
    """يحفظ بيانات حساب iCloud بمجلد الخبير الحالي"""
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'apple_id': apple_id.strip(), 'app_password': app_password.strip()}, f)


def load_credentials():
    """يرجع (apple_id, app_password) للخبير الحالي — نصين فاضيين لو ما فيه بيانات محفوظة"""
    _migrate_if_needed()
    try:
        path = _config_path()
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
                return data.get('apple_id', ''), data.get('app_password', '')
    except Exception:
        pass
    return '', ''


def has_credentials():
    """تستخدمها أي وحدة ثانية للتأكد من وجود حساب مربوط قبل أي محاولة فعلية"""
    apple_id, app_password = load_credentials()
    return bool(apple_id and app_password)


def _get_calendars():
    """يتصل بـiCloud ويرجع كل التقاويم المتاحة بالحساب (قائمة كاملة، لا تقويم واحد)"""
    import caldav
    apple_id, app_password = load_credentials()
    if not apple_id or not app_password:
        raise ValueError("لا يوجد حساب iCloud محفوظ بالإعدادات")

    client = caldav.DAVClient(
        url="https://caldav.icloud.com/",
        username=apple_id,
        password=app_password,
    )
    principal = client.principal()
    calendars = principal.calendars()
    if not calendars:
        raise ValueError("لا يوجد أي تقويم متاح بهذا الحساب")
    return calendars


def test_connection():
    """
    يتأكد من الاتصال **وقدرة الكتابة الفعلية** — مجرد عرض قائمة
    التقاويم بنجاح لا يكفي (بعضها يظهر بالقائمة وهو غير قابل للكتابة
    فعليًا). ننشئ موعد تجريبي بتاريخ بعيد جدًا بالمستقبل (صفر تعارض
    حقيقي مع أي موعد فعلي) وننجّربه على كل تقويم بالترتيب، ونحذفه
    فورًا بعد التأكد. يرجع (True, اسم_التقويم_الذي_نجح) أو
    (False, نص_الخطأ).
    """
    try:
        calendars = _get_calendars()
    except Exception as e:
        return False, str(e)

    import uuid
    from icalendar import Calendar, Event

    test_start = datetime.datetime.now() + datetime.timedelta(days=365 * 5)
    last_error = "تعذرت الكتابة على أي تقويم متاح بهذا الحساب"

    for cal in calendars:
        try:
            ical = Calendar()
            ical.add('prodid', '-//ExpertApp//ConnectionTest//AR')
            ical.add('version', '2.0')
            event = Event()
            event.add('summary', '_ExpertApp_connection_test_')
            event.add('dtstart', test_start)
            event.add('dtend', test_start + datetime.timedelta(minutes=10))
            event.add('dtstamp', datetime.datetime.now())
            event.add('uid', str(uuid.uuid4()))
            ical.add_component(event)

            saved = cal.save_event(ical.to_ical().decode('utf-8'))
            try:
                saved.delete()
            except Exception:
                pass
            return True, (cal.name or "تقويم بدون اسم")
        except Exception as e:
            last_error = str(e)
            continue

    return False, last_error


def _find_existing_event_by_summary(cal, summary):
    """
    يدوّر عن أي موعد بنفس العنوان (أي تاريخ — يغطي حالة تغيّر تاريخ
    الجلسة كذلك) بنطاق واسع حول اليوم. يرجع الموعد لو لقاه، أو None.

    نستخدم البحث بنطاق تاريخ (date_search) لا بمعرّف فريد (UID) —
    الأول معيار CalDAV أساسي مدعوم بثبات حتى مع iCloud، بعكس البحث
    بـUID المعروف بعدم موثوقيته تحديدًا على خوادم iCloud.
    """
    start = datetime.datetime.now() - datetime.timedelta(days=30)
    end = datetime.datetime.now() + datetime.timedelta(days=365)
    try:
        events = cal.date_search(start, end)
        for ev in events:
            try:
                ev.load()
                comp = ev.icalendar_component
                if str(comp.get('summary', '')) == summary:
                    return ev
            except Exception:
                continue
    except Exception:
        pass
    return None


def add_calendar_event(summary, start_datetime, duration_minutes=60, description=''):
    """
    يضيف موعد جديد بتقويم iCloud — يجرّب الكتابة على كل تقويم متاح
    بالحساب بالترتيب، ويتوقف عند أول تقويم ينجح فيه فعليًا (بعض
    تقاويم iCloud تظهر بالقائمة لكنها غير قابلة للكتابة، فما نفترض
    "أول تقويم" هو الصحيح أبدًا).

    لو فيه موعد سابق بنفس العنوان (مثلاً نفس رقم الخبرة) بنفس
    التقويم الناجح — يُحذف أول، ثم يُنشأ الجديد. تجديد فعلي بدل
    تكرار، حتى لو تغيّر تاريخ الجلسة بالكامل.

    start_datetime: كائن datetime.datetime (بالتوقيت المحلي للجهاز).

    لا ترفع أي استثناء — تُستخدم من مسارات تلقائية (تسجيل جلسة بالنظام)
    وفشل المزامنة هنا ما يجب يوقف أو يفشّل العملية الأساسية. يرجع
    (True, None) عند النجاح، أو (False, نص_الخطأ) عند الفشل.
    """
    if not has_credentials():
        return False, "لا يوجد حساب iCloud مربوط"

    try:
        calendars = _get_calendars()
    except Exception as e:
        return False, str(e)

    import uuid
    from icalendar import Calendar, Event

    last_error = "تعذرت الكتابة على أي تقويم متاح بهذا الحساب"

    for cal in calendars:
        try:
            existing = _find_existing_event_by_summary(cal, summary)
            if existing:
                try:
                    existing.delete()
                except Exception:
                    pass

            end_datetime = start_datetime + datetime.timedelta(minutes=duration_minutes)

            ical = Calendar()
            ical.add('prodid', '-//ExpertApp//Sessions//AR')
            ical.add('version', '2.0')

            event = Event()
            event.add('summary', summary)
            event.add('dtstart', start_datetime)
            event.add('dtend', end_datetime)
            event.add('dtstamp', datetime.datetime.now())
            event.add('uid', str(uuid.uuid4()))
            if description:
                event.add('description', description)
            ical.add_component(event)

            cal.save_event(ical.to_ical().decode('utf-8'))
            return True, None
        except Exception as e:
            last_error = str(e)
            continue

    return False, last_error
