"""سكربت تجربة مستقل لوكيل Copilot Studio عبر Microsoft 365 Agents SDK.

لا يلمس البرنامج. يعتمد على الحزمة microsoft-agents-copilotstudio-client
(CopilotClient / ConnectionSettings / PowerPlatformEnvironment) وMSAL تفاعلي.

الإعداد (متغيرات بيئة أو probe.ini بجانب السكربت؛ الملف خارج git):
    COPILOT_CONNECTION_STRING  أو  [probe] connection_string   (رابط Connection string من قناة Copilot Studio)
    COPILOT_TENANT_ID          أو  [probe] tenant_id
    COPILOT_CLIENT_ID          أو  [probe] client_id

التشغيل:  .venv\\Scripts\\python copilot_agent_probe.py
"""
from __future__ import annotations

import asyncio
import configparser
import logging
import os
import re
import sys
import time
from importlib.metadata import version
from pathlib import Path

HERE = Path(__file__).resolve().parent
INI_PATH = HERE / "probe.ini"
CACHE_PATH = HERE / ".token_cache.bin"  # خارج git (انظر .gitignore)

MSG1 = "اكتب جملة عربية قصيرة تعرّف نفسك"
MARKER = "خاتمة٧٣٩"

# جمل عامة مختلقة، ليست من أي قضية
_SENTENCES = [
    "في مدينة ساحلية صغيرة كان يعيش بستاني عجوز يعتني بحديقة واسعة مليئة بأشجار الليمون والزيتون.",
    "كان يستيقظ كل صباح قبل الفجر ليسقي الأشجار ويستمع إلى أصوات الطيور القادمة من التلال البعيدة.",
    "وفي أحد الأيام وصل إلى القرية تاجر متجول يحمل صناديق من البذور النادرة وأدوات زراعية غريبة الشكل.",
    "اشترى البستاني بعض البذور وجرّب زراعتها في زاوية مهملة من الحديقة، وراح يراقب نموها يوماً بعد يوم.",
    "مرّت الأسابيع وظهرت نباتات بأوراق فضية لم يرَ مثلها أحد في تلك الناحية، فتجمّع الجيران ليشاهدوها.",
    "تحدّث الناس عن رائحتها الحلوة وعن لونها الذي يتغير مع ضوء الشمس، وسمّوها زهرة الصباح.",
    "قرر البستاني أن يوزّع شتلاتها على كل بيت في القرية، فازدانت الشرفات والأسطح بخضرة جديدة.",
    "وفي موسم الحصاد أقام أهل القرية مهرجاناً صغيراً بالموسيقى والخبز الطازج والعصائر الباردة.",
    "جلس الأطفال حول البستاني يسألونه عن سرّ يده الخضراء، فابتسم وقال إن السرّ هو الصبر والمحبة.",
    "ثم أخذهم في جولة بين الأحواض وعلّمهم كيف يميّزون التربة الجيدة وكيف يحفظون الماء في الصيف.",
]


def _long_text(target: int = 3000) -> str:
    parts: list[str] = []
    n, i = 0, 0
    while n < target:
        s = _SENTENCES[i % len(_SENTENCES)]
        parts.append(s)
        n += len(s) + 1
        i += 1
    body = " ".join(parts)[:target].rsplit(" ", 1)[0]
    return (
        "اقرأ النص التالي ثم لخّصه في ثلاثة أسطر.\n\n"
        + body
        + f"\n\nفي نهاية ردك اكتب الكلمة الأخيرة من النص كما وردت، وهي: {MARKER}"
    )


def _load_config() -> dict[str, str]:
    cfg = {
        "connection_string": os.environ.get("COPILOT_CONNECTION_STRING", ""),
        "tenant_id": os.environ.get("COPILOT_TENANT_ID", ""),
        "client_id": os.environ.get("COPILOT_CLIENT_ID", ""),
    }
    if INI_PATH.exists():
        ini = configparser.ConfigParser()
        ini.read(INI_PATH, encoding="utf-8")
        if ini.has_section("probe"):
            for k in cfg:
                if not cfg[k]:
                    cfg[k] = ini.get("probe", k, fallback="").strip()
    return cfg


def _fail(reason: str, fix: str) -> int:
    print(f"\n✗ فشل: {reason}\n  الحل المقترح: {fix}")
    return 1


# ربط رموز الأخطاء بالسبب والحل (بالعربية)
_AAD_HINTS = [
    ("AADSTS65001", "الصلاحية غير ممنوحة للتطبيق (لا موافقة مستخدم)",
     "في Entra ID: App registrations ← API permissions ← أضف Power Platform API (CopilotStudio.Copilots.Invoke) ثم وافق عليها."),
    ("AADSTS90094", "موافقة المسؤول مطلوبة",
     "اطلب من مسؤول المستأجر Grant admin consent للصلاحية CopilotStudio.Copilots.Invoke."),
    ("AADSTS65002", "موافقة المسؤول مطلوبة", "اطلب من المسؤول منح الموافقة على الصلاحية."),
    ("AADSTS500011", "واجهة Power Platform API غير موجودة في المستأجر",
     "ابحث عن Power Platform API في API permissions؛ إن لم تظهر فعّلها بـ New-AzADServicePrincipal -ApplicationId 8578e004-a5c6-46e7-913e-12f58912df43."),
    ("AADSTS700016", "معرّف التطبيق (client_id) غير موجود في هذا المستأجر",
     "راجع client_id وtenant_id في probe.ini، وتأكد أن التسجيل في المستأجر نفسه."),
    ("AADSTS90002", "معرّف المستأجر (tenant_id) غير صحيح", "راجع tenant_id."),
    ("AADSTS50020", "الحساب شخصي (Microsoft Account) أو من مستأجر آخر وهو غير مدعوم",
     "سجّل الدخول بحساب عمل/مدرسة (Entra ID) من المستأجر نفسه، لا بحساب hotmail/outlook/gmail الشخصي."),
    ("AADSTS50011", "عنوان إعادة التوجيه غير مسجّل",
     "في App registration ← Authentication أضف منصة Mobile and desktop بعنوان http://localhost ."),
    ("AADSTS7000218", "التطبيق مسجّل كعميل سري (confidential)",
     "فعّل Allow public client flows في Authentication."),
    ("AADSTS50076", "المصادقة متعددة العوامل مطلوبة", "أكمل MFA في نافذة المتصفح."),
    ("AADSTS53003", "سياسة وصول مشروط حظرت الدخول", "راجع مسؤول المستأجر بشأن Conditional Access."),
]


def _explain_auth_error(text: str) -> tuple[str, str]:
    for code, reason, fix in _AAD_HINTS:
        if code in text:
            return f"{reason} ({code})", fix
    code = re.search(r"AADSTS\d+", text)
    return (f"رفض تسجيل الدخول ({code.group(0) if code else 'غير معروف'})",
            "راجع رمز الخطأ في توثيق Entra ID، وتأكد من إعدادات التسجيل والصلاحيات.")


def _explain_http(status: int) -> tuple[str, str]:
    table = {
        401: ("الرمز مرفوض (401): الجمهور/المستأجر خطأ أو الرمز منتهٍ",
              "تأكد أن tenant_id وclient_id صحيحان، واحذف .token_cache.bin ثم أعد المحاولة."),
        403: ("لا صلاحية لاستدعاء الوكيل (403)",
              "امنح الصلاحية CopilotStudio.Copilots.Invoke ووافق عليها، وتأكد أن الوكيل مشارك مع هذا الحساب، وأن المصادقة في الوكيل مضبوطة على «Authenticate with Microsoft»."),
        404: ("الوكيل غير موجود أو لم يُنشر (404)",
              "في Copilot Studio اضغط Publish للوكيل، وتأكد أن رابط Connection string منسوخ من Channels ← Web app/Native app."),
        429: ("تجاوز حد الطلبات (429)", "انتظر قليلاً ثم أعد المحاولة."),
    }
    if status in table:
        return table[status]
    if status >= 500:
        return f"خطأ في خدمة Copilot Studio ({status})", "أعد المحاولة لاحقاً؛ وإن تكرر فراجع حالة الخدمة."
    return f"استجابة غير متوقعة ({status})", "تحقق من رابط الاتصال والمستأجر."


def _acquire_token(tenant_id: str, client_id: str, scope: str) -> str:
    import msal
    from msal_extensions import FilePersistence, PersistedTokenCache, build_encrypted_persistence

    try:
        persistence = build_encrypted_persistence(str(CACHE_PATH))  # DPAPI على ويندوز
    except Exception:
        persistence = FilePersistence(str(CACHE_PATH))
    cache = PersistedTokenCache(persistence)
    app = msal.PublicClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        token_cache=cache,
    )
    result = None
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent([scope], account=accounts[0])
    if not result:
        print("… سيُفتح المتصفح لتسجيل الدخول")
        result = app.acquire_token_interactive([scope])
    if "access_token" not in result:
        raise PermissionError(f"{result.get('error', '')} {result.get('error_description', '')}")
    return result["access_token"]


async def _ask(client, text: str) -> tuple[str, float]:
    """يرسل سؤالاً ويعيد (نص الرد، الزمن بالثواني)."""
    t0 = time.perf_counter()
    chunks: list[str] = []
    async for act in client.ask_question(text):
        if act.type == "message" and act.text:
            chunks.append(act.text)
    return "\n".join(chunks), time.perf_counter() - t0


async def _run(cfg: dict[str, str]) -> int:
    import aiohttp
    from microsoft_agents.copilotstudio.client import ConnectionSettings, CopilotClient, PowerPlatformEnvironment

    settings = ConnectionSettings(
        environment_id="", agent_identifier="", direct_connect_url=cfg["connection_string"]
    )
    scope = PowerPlatformEnvironment.get_token_audience(settings=settings)

    try:
        token = await asyncio.to_thread(_acquire_token, cfg["tenant_id"], cfg["client_id"], scope)
    except Exception as e:  # noqa: BLE001
        reason, fix = _explain_auth_error(str(e))
        return _fail(reason, fix)
    print("✓ تم تسجيل الدخول")

    client = CopilotClient(settings, token)
    try:
        async for _ in client.start_conversation(True):
            pass
        print("✓ بدأت المحادثة")

        print(f"\n— الرسالة 1: {MSG1}")
        reply, dt = await _ask(client, MSG1)
        print(f"الرد ({dt:.1f}ث): {reply or '(فارغ)'}")
        if not reply.strip():
            return _fail("ردّ الوكيل فارغ", "تأكد أن الوكيل منشور وله موضوع/معرفة يردّ بها، وأن نموذج التوليد مفعّل.")

        long_msg = _long_text()
        print(f"\n— الرسالة 2: نص عربي طويل ({len(long_msg)} حرفاً)")
        reply2, dt2 = await _ask(client, long_msg)
        print(f"الرد ({dt2:.1f}ث، {len(reply2)} حرفاً): {reply2 or '(فارغ)'}")
        saw_marker = MARKER in reply2
        ends_ok = bool(reply2.strip()) and reply2.strip()[-1] in ".!؟?…\"»)" or saw_marker
        print(f"\nزمن الرد: {dt2:.1f}ث")
        print(f"اقتُطع؟ {'لا' if (saw_marker and ends_ok) else 'محتمل — راجع الرد أعلاه'}"
              f" (علامة نهاية النص {'وردت' if saw_marker else 'لم ترد'}، نهاية الرد {'سليمة' if ends_ok else 'مبتورة'})")
        return 0
    except aiohttp.ClientError as e:
        m = re.search(r"(\d{3})", str(e))
        if m:
            reason, fix = _explain_http(int(m.group(1)))
        else:
            reason, fix = "تعذّر الاتصال بالخدمة", "تحقق من الإنترنت ومن صحة رابط الاتصال."
        return _fail(reason, fix)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    logging.disable(logging.CRITICAL)  #لا سجلات قد تحوي أسرارًا
    print(f"microsoft-agents-copilotstudio-client {version('microsoft-agents-copilotstudio-client')}")
    cfg = _load_config()
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        return _fail(f"إعدادات ناقصة: {', '.join(missing)}",
                     f"ضعها في متغيرات بيئة COPILOT_* أو في {INI_PATH.name} تحت [probe].")
    if not cfg["connection_string"].lower().startswith("https://"):
        return _fail("connection_string ليس رابطاً صالحاً",
                     "انسخه من Copilot Studio ← Channels ← Web app أو Native app ← Connection string.")
    try:
        return asyncio.run(_run(cfg))
    except Exception as e:  # noqa: BLE001
        return _fail(f"خطأ غير متوقع ({type(e).__name__})", "راجع الإعدادات؛ لم تُطبع تفاصيل لتجنب تسريب أسرار.")


if __name__ == "__main__":
    sys.exit(main())
