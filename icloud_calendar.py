# ===== icloud_calendar.py — مزامنة مواعيد الجلسات تلقائيًا بتقويم iCloud =====
"""
يضيف موعد الجلسات تلقائيًا للتقويم الافتراضي بالآيفون (عبر iCloud،
بروتوكول CalDAV). كل خبير يربط حسابه الخاص بنفسه من صفحة الإعدادات —
نفس فكرة مفتاح Gemini تمامًا (بيانات محلية، شخصية، لكل مستخدم).

يحتاج Apple ID + App-Specific Password (يُولَّد من appleid.apple.com
→ الأمان → كلمات مرور خاصة بالتطبيق) — مب كلمة مرور الحساب الأصلية.

═══════════════════════════════════════════════════════════════════════
⚠️ شبكة الوزارة تحجب Apple (17/11/2026)
═══════════════════════════════════════════════════════════════════════
القياس: من جهاز خارج الوزارة — DNS ✓ · TCP 443 بـ0.14ث · TLS بـ0.18ث ·
رد Apple (401) بـ0.41ث ✅ ⟵ الخوادم سليمة. وبالوزارة: **read timeout**
(الطلب اتبعث وما وصل رد) ⟵ جدار حماية يقبل الاتصال ويبتلع حمولة TLS.

═══════════════════════════════════════════════════════════════════════
⚠️ تجاوز البورت — **صامت بالكامل** (ما فيه أي زر ولا نافذة ولا إعداد)
═══════════════════════════════════════════════════════════════════════
المزامنة **ما تحتاج المستخدم يفعل شي**: كل محاولة إضافة تمرّ بسلسلة
محاولات **تلقائية** بالترتيب (المباشرة **8 ث** · الوسيط **12 ث**):

  1) **مباشر** (CalDAV) من جهاز المستخدم.
  2) **وسيط سحابي** (Edge Function على Supabase) — الخادم يوصل لـApple
     من خارج شبكة الدوام ⟵ **هذا هو تجاوز البورت المقفل**. كلمة المرور
     تُرسل **مشفّرة بمفتاح RSA عام** (المفتاح الخاص Secret عند الخادم
     بس) ⟵ ولا تُخزَّن أي بيانات على السحابة (طلب ورد فقط).
  3) **مباشر مرة ثانية** — لو الجدار أفلّت أول اتصال.

لو فشلت الثلاث ⟵ **رسالة وحدة نصية** (البورت مقفل) — بلا أزرار وبلا
تحويل لملفات: يقرر الخبير بنفسه.

⚠️ **ما فيه أي عنصر مرئي** للتجاوز: لا checkbox ولا نافذة بروكسي ولا زر
«فحص» ولا زر «إعدادات المزامنة». كل شي يصير بالخلفية تلقائياً.

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
     الكتابة الفعلية (تنشئ موعد تجريبي بعيدًا بالمستقبل وتحذفه
     فورًا)، مب فقط من نجاح تسجيل الدخول وعرض القوائم.
  4) بيانات الحساب تُحفظ بمجلد خاص بكل خبير على حدة (current_expert.py)
     — مب مجلد عام يتشاركه كل من يستخدم نفس الجهاز، لأن كل خبير له
     حساب iCloud شخصي مختلف.
"""
import os
import json
import base64
import datetime
from current_expert import expert_data_dir

_OLD_CONFIG_PATH = os.path.join(
    os.environ.get('LOCALAPPDATA', ''), 'ExpertApp', 'icloud_calendar.json'
)

#: مهلة الاتصال المباشر (ثوانٍ) — قصيرة عمداً: نبي نكتشف الحجب بسرعة
#: بدل ما نجمّد المستخدم 30 ثانية (الافتراضي القديم كان 30).
CALDAV_TIMEOUT = 8

#: مهلة محاولة الوسيط السحابي (ثوانٍ) — **12 ث** (مو 8):
#: أول نداء بعد خمول الدالة (cold start) قيس بـ5–6.2 ث ⟵ بمهلة 8 ث
#: كان ممكن تفشل المحاولة الأولى قبل ما الخادم يكمّل الكتابة. والمستخدم
#: ما ينتظر (الطلب كله بالخلفية).
RELAY_TIMEOUT = 12

#: رابط دالة الوسيط على Supabase (Edge Function)
RELAY_URL = ("https://xzgwlqfsdwbjoxdewffy.supabase.co"
             "/functions/v1/calendar-relay")
#: رمز مشترك بين البرنامج والخادم (عند الخادم: Secret اسمه RELAY_TOKEN)
RELAY_TOKEN = "BH5vBfqu_CQFFalUG0s3REizjOnhzEaUqhl8yPXIyZA"
#: المفتاح العام للوسيط — تشفير كلمة مرور iCloud قبل إرسالها (RSA-OAEP)
#: (المفتاح الخاص Secret عند الخادم — **ما ينكتب بالبرنامج ولا بالمستودع**)
RELAY_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAjiIy+1UHMJ0JH7cP9vSf
dwbnK4iViRoNP0mnRZ4bYnD9idLq3HUWim49sCv7HSaaA2I653yYmUuHEnPS+2Pp
noJaljJuIPHCntpf+gjmuBfUvpi1pUr9YEy2fONhIeNOCCFZCDsP5rX4mgUQXs85
/MdJbrJQ9oAimA4w2WhIIJN+ONJCZsyQcisbSxb7WeR3V2cvoLnkccOgrX3PXbPf
HQYshreVSioP5724QPoOJKjtEZy3Ug/IL6mqeij3yH1WbJ4OedeJkeBIJJOIYfJt
U7LiO6YK1qvHsfFrQ/NARxfCqGETypqv7uhnsheTVkCLgu+UeVc5N6ynFEmwAYp/
3QIDAQAB
-----END PUBLIC KEY-----"""

#: عنوان الموعد التجريبي أثناء فحص الاتصال (بيُحذف فوراً)
TEST_SUMMARY = '_ExpertApp_connection_test_'

#: رسالة الفشل النهائية (نص فقط — بلا أزرار وبلا تحويل لملفات)
BLOCKED_MESSAGE = (
    'تعذّرت إضافة الجلسة لتقويم iCloud — خدمة iCloud محجوبة في شبكة '
    'الدوام (البورت مقفل)، والمحاولات التلقائية الثلاث ما نجحت. '
    'جرّب من شبكة ثانية، أو أضف الموعد يدويًا بتقويمك.')

#: لو السبب بيانات الحساب (مو البورت)
AUTH_MESSAGE = (
    'تعذّرت إضافة الجلسة لتقويم iCloud — بيانات الحساب غير صحيحة. '
    'راجع Apple ID وكلمة المرور الخاصة بالتطبيق من صفحة الإعدادات.')


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
    """يفظ بيانات حساب iCloud بمجلد الخبير الحالي"""
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


# ---------------------------------------------------------------------------
# الأخطاء — ترجمة سطر بايثون إلى رسالة مفهومة
# ---------------------------------------------------------------------------

#: كلمات تدل إن الخطأ من الشبكة (يعني الوسيط/المحاولة الثانية تنفع)
_NET_HINTS = ('timeout', 'timed out', 'connection', 'connect', 'ssl',
              'proxy', 'max retries', 'network', 'unreachable', 'reset by peer',
              'temporary failure', 'name or service not known', 'nodename nor servname',
              'bad gateway', '502', '503', '504')


def is_network_error(exc):
    """هل هذا الخطأ من الشبكة (يعني المحاولة التالية تنفع)؟"""
    text = str(exc).lower()
    return any(k in text for k in _NET_HINTS)


def classify_error(exc):
    """
    يصنّف الخطأ:
      'auth'    ⟵ بيانات الحساب غلط (ما فايدة تجريب المسارات)
      'network' ⟵ الشبكة/البورت (المحاولة التالية تنفع)
      'other'   ⟵ أي شي ثاني
    """
    low = str(exc).lower()
    if ('unauthorized' in low or '401' in low
            or ('invalid' in low and 'credential' in low)
            or 'بيانات غير صحيحة' in low):
        return 'auth'
    if is_network_error(exc):
        return 'network'
    return 'other'


def friendly_error(exc):
    """يحوّل الاستثناء التقني إلى رسالة عربية مفهومة (للسجل الداخلي)."""
    text = str(exc)
    low = text.lower()
    if 'timed out' in low or 'timeout' in low:
        return ('انتهت مهلة الاتصال (%d ث) — خدمة iCloud محجوبة من هالشبكة.'
                % CALDAV_TIMEOUT)
    if 'unauthorized' in low or '401' in low:
        return ('بيانات حساب iCloud غير صحيحة — تأكد من Apple ID وكلمة المرور '
                'الخاصة بالتطبيق (وليس كلمة مرور الحساب).')
    if 'certificate' in low or 'ssl' in low:
        return 'مشكلة شهادة الأمان — قد تكون شبكة الدوام تفحص اتصالات TLS.'
    if is_network_error(exc):
        return ('ما قدرنا نوصل لخدمة iCloud من هالشبكة (%s).'
                % text.split('\n')[0][:120])
    return text


# ---------------------------------------------------------------------------
# الاتصال المباشر (CalDAV)
# ---------------------------------------------------------------------------

def _dav_client():
    """عميل CalDAV — بمهلة قصيرة (8 ث)."""
    import caldav
    apple_id, app_password = load_credentials()
    if not apple_id or not app_password:
        raise ValueError("لا يوجد حساب iCloud محفوظ بالإعدادات")
    return caldav.DAVClient(
        url="https://caldav.icloud.com/",
        username=apple_id,
        password=app_password,
        timeout=CALDAV_TIMEOUT,
    )


def _get_calendars():
    """يتصل بـiCloud ويرجع كل التقاويم المتاحة بالحساب (قائمة كاملة، لا تقويم واحد)"""
    client = _dav_client()
    principal = client.principal()
    calendars = principal.calendars()
    if not calendars:
        raise ValueError("لا يوجد أي تقويم متاح بهذا الحساب")
    return calendars


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


def _build_ics(summary, start_datetime, duration_minutes, description):
    """يبني ملف ICS (نفس الصيغة بالعميل والوسيط)."""
    import uuid
    from icalendar import Calendar, Event

    ical = Calendar()
    ical.add('prodid', '-//ExpertApp//Sessions//AR')
    ical.add('version', '2.0')

    event = Event()
    event.add('summary', summary)
    event.add('dtstart', start_datetime)
    event.add('dtend', start_datetime + datetime.timedelta(minutes=duration_minutes))
    event.add('dtstamp', datetime.datetime.now())
    event.add('uid', str(uuid.uuid4()))
    if description:
        event.add('description', description)
    ical.add_component(event)
    return ical.to_ical().decode('utf-8')


def _write_direct(summary, start_datetime, duration_minutes=60, description=''):
    """
    محاولة **مباشرة** على iCloud (CalDAV).

    يرجع (True, None, None) عند النجاح، أو (False, الرسالة, نوع_الخطأ).
    يجرّب الكتابة على كل تقويم متاح بالحساب بالترتيب، ويتوقف عند أول
    تقويم ينجح فيه فعليًا (بعض تقاويم iCloud تظهر بالقائمة لكنها غير
    قابلة للكتابة، فما نفترض «أول تقويم» هو الصحيح أبداً).

    لو فيه موعد سابق بنفس العنوان (مثلاً نفس رقم الخبرة) — يُحذف أول،
    ثم يُنشأ الجديد. تجديد فعلي بدل تكرار.
    """
    try:
        calendars = _get_calendars()
    except Exception as e:
        return False, friendly_error(e), classify_error(e)

    last_error = "تعذرت الكتابة على أي تقويم متاح بهذا الحساب"
    last_kind = 'other'
    for cal in calendars:
        try:
            existing = _find_existing_event_by_summary(cal, summary)
            if existing:
                try:
                    existing.delete()
                except Exception:
                    pass

            ics = _build_ics(summary, start_datetime, duration_minutes, description)
            cal.save_event(ics)
            return True, None, None
        except Exception as e:
            last_error = str(e)
            last_kind = classify_error(e)
            continue
    return False, friendly_error(last_error), last_kind


# ---------------------------------------------------------------------------
# المسار عبر وسيط السحابة (Supabase) — هذا هو **تجاوز البورت**
# ---------------------------------------------------------------------------

def add_calendar_event_via_relay(summary, start_datetime, duration_minutes=60,
                                  description='', delete_after=False):
    """
    يرسل الموعد **لوسيط السحابي** (Edge Function على Supabase) والوسيط
    هو اللي يكتبه على iCloud ⟵ يشتغل من شبكات محجوبة (شبكة الدوام).

    كلمة المرور تُرسل **مشفّرة** (RSA-OAEP بمفتاح عام) — والمفتاح الخاص
    عند الخادم بس. ولا يُخزَّن أي شي على السحابة (طلب ورد فقط).

    delete_after=True ⟵ الخادم يحذف الموعد فور كتابته (للفحص فقط).

    يرجّع (True, None) عند النجاح، أو (False, نص_الخطأ).
    """
    try:
        import requests
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        apple_id, app_password = load_credentials()
        if not apple_id or not app_password:
            return False, "لا يوجد حساب iCloud مربوط"

        key = serialization.load_pem_public_key(RELAY_PUBLIC_KEY_PEM.encode('utf-8'))
        enc = key.encrypt(
            app_password.encode('utf-8'),
            padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                         algorithm=hashes.SHA256(), label=None))

        payload = {
            'apple_id': apple_id,
            'password_b64': base64.b64encode(enc).decode('ascii'),
            'summary': summary,
            'start': start_datetime.isoformat(),
            'duration_minutes': duration_minutes,
            'description': description,
        }
        if delete_after:
            payload['delete_after'] = True
        headers = {'Content-Type': 'application/json', 'x-relay-token': RELAY_TOKEN}
        r = requests.post(RELAY_URL, json=payload, headers=headers,
                          timeout=RELAY_TIMEOUT)
        if r.status_code != 200:
            return False, ('الوسيط ما رد (%s) — الخدمة السحابية غير متاحة '
                           'حالياً.' % r.status_code)
        data = r.json() or {}
        if data.get('ok'):
            return True, None
        return False, data.get('error') or 'فشل غير معروف من الوسيط'
    except Exception as e:
        return False, friendly_error(e)


# ---------------------------------------------------------------------------
# المسار المفضّل — **تلقائي بالكامل** (ما فيه أي إعداد ولا زر)
# ---------------------------------------------------------------------------

def add_calendar_event(summary, start_datetime, duration_minutes=60,
                        description=''):
    """
    يضيف موعد جديد بتقويم iCloud — **بصمت** (ينادى من خيط خلفي).

    ⚠️ **سلسلة المحاولات التلقائية** (المباشر 8 ث · الوسيط 12 ث):
      1) **مباشر** (CalDAV) — لو الشبكة تسمح.
      2) **وسيط سحابي** — يتصل بـApple من خارج شبكة الدوام ⟵ **تجاوز
         البورت المقفل** (وضع شبكة الوزارة).
      3) **مباشر مرة ثانية** — لو الجدار أفلّت أول اتصال.

    لو فشلت الثلاث ⟵ **رسالة وحدة نصية** — بلا أزرار وبلا تحويل
    لملفات (يقرر الخبير بنفسه).

    start_datetime: كائن datetime.datetime (بالتوقيت المحلي للجهاز).

    لا ترفع أي استثناء — تُستخدم من مسارات تلقائية (تسجيل جلسة بالنظام)
    وفشل المزامنة هنا ما يجب يوقف أو يفشّل العملية الأساسية. يرجع
    (True, None) عند النجاح، أو (False, نص_الخطأ) عند الفشل.
    """
    if not has_credentials():
        return False, "لا يوجد حساب iCloud مربوط"

    kinds = []

    # 1) محاولة مباشرة
    ok, err, kind = _write_direct(summary, start_datetime,
                                   duration_minutes, description)
    if ok:
        return True, None
    kinds.append(kind or 'other')

    # 2) تجاوز البورت — الوسيط السحابي
    ok, err = add_calendar_event_via_relay(summary, start_datetime,
                                            duration_minutes, description)
    if ok:
        return True, None
    kinds.append(classify_error(err))

    # 3) محاولة مباشرة ثانية
    ok, err, kind = _write_direct(summary, start_datetime,
                                   duration_minutes, description)
    if ok:
        return True, None
    kinds.append(kind or 'other')

    return False, (AUTH_MESSAGE if 'auth' in kinds else BLOCKED_MESSAGE)


def _test_direct():
    """
    فحص مباشر: ينشئ موعدًا تجريبيًا بعيدًا بالمستقبل ويتأكد من **الكتابة
    الفعلية** (مو مجرد عرض قائمة التقاويم)، ثم يحذفه فورًا.
    يرجع (True, اسم_التقويم) أو (False, الرسالة).
    """
    try:
        calendars = _get_calendars()
    except Exception as e:
        return False, friendly_error(e)

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
            event.add('summary', TEST_SUMMARY)
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

    return False, friendly_error(last_error)


def test_connection():
    """
    فحص الاتصال — **تلقائي بالكامل** (نفس مسارات الإضافة، بس بترتيب أسرع).

    ⚠️ هنا **الوسيط أولاً**: بشبكة الدوام (Apple محجوب) يوصل بنتيجة خلال
    ~3 ث بدل ما ننتظر 8 ث على المباشر ونفشل. وبعده نجرّب المباشر — فلو
    الشبكة تسمح نشوف التقويم المحلي.

    يرجّع (True, اسم_التقويم_أو_المصدر) أو (False, نص_الخطأ).
    """
    # 1) الوسيط السحابي (تجاوز البورت) — يكتب موعد تجريبي ويحذفه فورًا
    ok, err = add_calendar_event_via_relay(
        TEST_SUMMARY,
        datetime.datetime.now() + datetime.timedelta(days=365 * 5),
        duration_minutes=10, delete_after=True)
    if ok:
        return True, 'الوسيط السحابي'
    kind = classify_error(err)

    # 2) مباشر — تأكد من الكتابة الفعلية على التقويم المحلي
    ok, msg = _test_direct()
    if ok:
        return True, msg

    return False, (AUTH_MESSAGE if kind == 'auth' else BLOCKED_MESSAGE)
