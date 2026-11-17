// ===== supabase/functions/calendar-relay/index.ts =====
// وسيط مزامنة التقويم — يضيف الموعد على تقويم iCloud من **خارج** شبكة الدوام.
//
// ليش: شبكة وزارة العدل تحجب caldav.icloud.com (الطلب يطلع وما يوصل رد).
// هذا الخادم يوصل لـApple عادي، ف يضيف الموعد للآيفون مباشرة.
//
// ⚠️ لا يخزّن أي شي: طلب ورد فقط (وكلمة المرور تصل **مشفّرة** بمفتاح RSA
//    عام — والمفتاح الخاص Secret عند هذا الخادم بس).
//
// ── الإعداد (مرة وحدة) ─────────────────────────────────────────────────
//  1) نشر الدالة (من مجلد المشروع):
//       npx supabase functions deploy calendar-relay \
//         --remote=xzgwlqfsdwbjoxdewffy --no-verify-jwt
//     (‏--no-verify-jwt لأن البرنامج ما عنده JWT — الحارس هو الرمز المشترك)
//  2) ضبط الأسرار:
//       npx supabase secrets set --remote=xzgwlqfsdwbjoxdewffy \
//         --env-file <ملف فيه RELAY_TOKEN و RELAY_PRIVATE_KEY>
//  3) (اختياري) من Dashboard → Edge Functions → calendar-relay → Details
//     ⟵ Redeploy بعد أي تعديل.
// ─────────────────────────────────────────────────────────────────────────

const ROOT_URL = 'https://caldav.icloud.com/';

function basicAuth(user: string, pass: string): string {
  return 'Basic ' + btoa(`${user}:${pass}`);
}

// ── فك تشفير RSA-OAEP (SHA-256) ─────────────────────────────────────────
async function decryptPassword(payloadB64: string): Promise<string> {
  const pem = Deno.env.get('RELAY_PRIVATE_KEY') ?? '';
  if (!pem) throw new Error('مفتاح الخادم الخاص غير مضبوط (RELAY_PRIVATE_KEY)');
  const keyPem = pem.replace(/\\n/g, '\n');
  const der = Uint8Array.from(atob(keyPem
    .replace(/-----BEGIN PRIVATE KEY-----/g, '')
    .replace(/-----END PRIVATE KEY-----/g, '')
    .replace(/\s+/g, '')), (c) => c.charCodeAt(0));
  const key = await crypto.subtle.importKey(
    'pkcs8', der, { name: 'RSA-OAEP', hash: 'SHA-256' }, false, ['decrypt']);
  const enc = Uint8Array.from(atob(payloadB64), (c) => c.charCodeAt(0));
  const plain = await crypto.subtle.decrypt({ name: 'RSA-OAEP' }, key, enc);
  return new TextDecoder().decode(plain);
}

// ── أدوات XML بسيطة (tolerant) ─────────────────────────────────────────

/** كل بلوك <D:response>…</D:response> — وحدة المعالجة الوحيدة الآمنة */
function responseBlocks(xml: string): string[] {
  const out: string[] = [];
  const re = /<[^>]*response[^>]*>[\s\S]*?<\/[^>]*response>/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(xml)) !== null) out.push(m[0]);
  return out;
}

function tagValue(xml: string, tag: string): string {
  const m = xml.match(new RegExp(`<[^>]*${tag}[^>]*>([\\s\\S]*?)</[^>]*${tag}>`, 'i'));
  return m ? m[1].replace(/<[^>]+>/g, '').trim() : '';
}

function hrefOf(block: string): string {
  const m = block.match(/<[^>]*href[^>]*>([\s\S]*?)<\/[^>]*href>/i);
  return m ? m[1].trim() : '';
}

function decodeXml(s: string): string {
  return s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'").replace(/&amp;/g, '&');
}

/**
 * ⚠️ العنوان موجود **نص عادي** داخل calendar-data (مو وسم XML):
 *    <C:calendar-data>BEGIN:VCALENDAR… SUMMARY:جلسة …</C:calendar-data>
 * فقرأه سطر SUMMARY مباشرة، ونرجّعه «مفكوك escapes» للمقارنة.
 */
function icsSummary(block: string): string {
  const m = block.match(/SUMMARY[^:\r\n]*:(.*)/i);
  if (!m) return '';
  return icsUnescape(decodeXml(m[1].trim()));
}

/** فك ترميز نصوص ICS (\\, \\; \\\\) — للمقارنة مع العنوان الأصلي */
function icsUnescape(s: string): string {
  return s.replace(/\\\\/g, '\\').replace(/\\;/g, ';').replace(/\\,/g, ',');
}

/** رابط مورد CalDAV — من الجذر دائماً (نفس ما يرسله caldav) */
function caldavUrl(href: string): string {
  if (href.startsWith('http')) return href;
  return new URL(href, ROOT_URL).toString();
}

// ── CalDAV ──────────────────────────────────────────────────────────────

/**
 * ⚠️ ترويسات Apple (iCloud) — **لازم تكون بالضبط**:
 *    Content-Type: text/xml  (مو application/xml — يرجّع multistatus فاضي)
 *    Accept: text/xml, text/calendar
 *    Depth: 1  (مطلوب على REPORT)
 */
const DAV_HEADERS: Record<string, string> = {
  'Content-Type': 'text/xml',
  'Accept': 'text/xml, text/calendar',
  'User-Agent': 'ExpertApp/1.2.12 (CalDAV)',
};

async function propfind(url: string, auth: string, body: string, depth: string) {
  const res = await fetch(url, {
    method: 'PROPFIND',
    headers: {
      ...DAV_HEADERS,
      Authorization: auth,
      Depth: depth,
    },
    body,
  });
  const text = await res.text();
  return { status: res.status, text };
}

/**
 * ⚠️ استعلام المواعيد لازم يكون **REPORT** مو PROPFIND —
 *    Apple (iCloud) يرجّع 400 على PROPFIND مع calendar-query.
 */
async function report(url: string, auth: string, body: string) {
  const res = await fetch(url, {
    method: 'REPORT',
    headers: {
      ...DAV_HEADERS,
      Authorization: auth,
      Depth: '1',
    },
    body,
  });
  const text = await res.text();
  return { status: res.status, text };
}

const PRINCIPAL_QUERY = `<?xml version="1.0" encoding="utf-8"?>
<D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><D:current-user-principal/></D:prop></D:propfind>`;

const HOME_SET_QUERY = `<?xml version="1.0" encoding="utf-8"?>
<D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><C:calendar-home-set/></D:prop></D:propfind>`;

const CALENDAR_QUERY = `<?xml version="1.0" encoding="utf-8"?>
<D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><D:resourcetype/><D:displayname/><C:supported-calendar-component-set/></D:prop></D:propfind>`;

function icsEscape(text: string): string {
  return (text || '').replace(/\\/g, '\\\\').replace(/;/g, '\\;')
    .replace(/,/g, '\\,').replace(/\r?\n/g, '\\n');
}

// ── الوقت: كل التواريخ محلية (floating) مثل المسار المباشر بالبايثون ────
interface LocalParts { y: number; mo: number; d: number; h: number; mi: number }

function parseLocal(iso: string): LocalParts | null {
  const m = (iso || '').match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
  if (!m) return null;
  return { y: +m[1], mo: +m[2], d: +m[3], h: +m[4], mi: +m[5] };
}

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

/** LocalParts → "20261118T080000" (وقت عائم — بدون Z) */
function stampOf(p: LocalParts): string {
  return `${p.y}${pad2(p.mo)}${pad2(p.d)}T${pad2(p.h)}${pad2(p.mi)}00`;
}

/** وقت UTC → "20261118T080000Z" (لـDTSTAMP ولاستعلام time-range) */
function utcStamp(date: Date): string {
  return date.toISOString().replace(/[-:]/g, '').replace(/\.\d+/, '');
}

function buildICS(summary: string, start: string, minutes: number,
                  description: string, uid: string): string {
  const p = parseLocal(start);
  if (!p) throw new Error('تاريخ البداية غير صالح');
  const dur = Math.max(5, Number(minutes) || 60);

  // ⚠️ نجمع المدة بالتاريخ المحلي (مو UTC) — حتى ما ينزاح DTEND بساعة
  //    حسب فرق التوقيت بين الجهاز والخادم.
  const endDate = new Date(p.y, p.mo - 1, p.d, p.h, p.mi + dur);
  const endLocal: LocalParts = {
    y: endDate.getFullYear(), mo: endDate.getMonth() + 1, d: endDate.getDate(),
    h: endDate.getHours(), mi: endDate.getMinutes(),
  };

  return [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//ExpertApp//Sessions//AR',
    'BEGIN:VEVENT',
    `UID:${uid}`,
    `DTSTAMP:${utcStamp(new Date())}`,
    `DTSTART:${stampOf(p)}`,
    `DTEND:${stampOf(endLocal)}`,
    `SUMMARY:${icsEscape(summary)}`,
    ...(description ? [`DESCRIPTION:${icsEscape(description)}`] : []),
    'END:VEVENT',
    'END:VCALENDAR',
    '',
  ].join('\r\n');
}

function uid(): string {
  return crypto.randomUUID();
}

interface Cal { href: string; name: string }

/**
 * قائمة تقاويم الحساب — **3 خطوات** (نفس تسلسل caldav اللي تنجح مع Apple):
 *   1) root ⟵ current-user-principal
 *   2) principal (Depth 0) ⟵ calendar-home-set  (⚠️ لازم Depth 0)
 *   3) home-set (Depth 1) ⟵ قائمة التقاويم
 *
 * ⚠️ home-set ممكن يكون على مستضيف **مختلف** (p114-caldav.icloud.com).
 */
async function listCalendars(auth: string): Promise<Cal[]> {
  const root = await propfind(ROOT_URL, auth, PRINCIPAL_QUERY, '0');
  if (root.status >= 400) throw new Error(appleBusy(root.status) ?? `تعذّر الوصول لـiCloud (${root.status})`);
  let principalHref = '';
  const m = root.text.match(/<[^>]*current-user-principal[^>]*>([\s\S]*?)<\/[^>]*current-user-principal>/i);
  if (m) {
    const h = m[1].match(/<[^>]*href[^>]*>([\s\S]*?)<\/[^>]*href>/i);
    if (h) principalHref = h[1].trim();
  }
  if (!principalHref) throw new Error('ما لقينا حسابك عند iCloud (بيانات غير صحيحة؟)');
  const principalUrl = caldavUrl(principalHref);

  const home = await propfind(principalUrl, auth, HOME_SET_QUERY, '0');
  if (home.status >= 400) throw new Error(appleBusy(home.status) ?? `تعذّر قراءة إعدادات الحساب (${home.status})`);
  let homeHref = '';
  const hm = home.text.match(/<[^>]*calendar-home-set[^>]*>([\s\S]*?)<\/[^>]*calendar-home-set>/i);
  if (hm) {
    const h = hm[1].match(/<[^>]*href[^>]*>([\s\S]*?)<\/[^>]*href>/i);
    if (h) homeHref = h[1].trim();
  }
  if (!homeHref) throw new Error('ما لقينا مجلد تقاويم الحساب');
  const homeUrl = homeHref.startsWith('http') ? homeHref : new URL(homeHref, ROOT_URL).toString();

  const res = await propfind(homeUrl, auth, CALENDAR_QUERY, '1');
  if (res.status >= 400) throw new Error(appleBusy(res.status) ?? `تعذّر قراءة التقاويم (${res.status})`);

  const out: Cal[] = [];
  for (const block of responseBlocks(res.text)) {
    // ⚠️ وسم التقويم عند Apple: <calendar xmlns="urn:ietf:params:xml:ns:caldav"/>
    //    ⟵ لازم نسمح بالصفات **بعد** اسم الوسم.
    if (!/<(?:[A-Za-z0-9_-]+:)?calendar(?:\s[^>]*)?\/>/i.test(block)) continue;
    const href = hrefOf(block);
    if (!href) continue;
    out.push({ href: caldavUrl(href), name: decodeXml(tagValue(block, 'displayname')) || 'تقويم' });
  }
  return out;
}

/**
 * ⚠️ Apple عنده سقف طلبات (Rate limit) — كل نداء يطلب 3 PROPFIND + REPORT + PUT.
 *    فنتذكر قائمة التقاويم 10 دقائق ⟵ الطلبات لأقل حد (REPORT + PUT بس).
 */
const calCache = new Map<string, { expires: number; cals: Cal[] }>();
const CAL_CACHE_MS = 10 * 60 * 1000;

/** رسالة واضحة لسقف طلبات Apple (مو «البورت مقفل») */
function appleBusy(status: number): string | null {
  if (status === 429 || status === 503) {
    return 'خدمة iCloud مشغولة مؤقتاً (تجاوزت سقف الطلبات) — أعد المحاولة بعد قليل.';
  }
  return null;
}

async function getCalendars(auth: string, appleId: string, force = false): Promise<Cal[]> {
  const hit = calCache.get(appleId);
  if (!force && hit && hit.expires > Date.now()) return hit.cals;
  const cals = await listCalendars(auth);
  calCache.set(appleId, { expires: Date.now() + CAL_CACHE_MS, cals });
  return cals;
}

/** يحذف الموعد القديم بنفس العنوان (تجديد بدل تكرار) — REPORT لا PROPFIND */
async function deleteExisting(auth: string, calHref: string, summary: string,
                              startIso: string): Promise<void> {
  const start = new Date(startIso);
  const from = new Date(start.getTime() - 30 * 86400000);
  const to = new Date(start.getTime() + 365 * 86400000);
  // ⚠️ time-range بصيغة UTC (حسب مواصفة CalDAV)
  const query = `<?xml version="1.0" encoding="utf-8"?>
<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
<D:prop><C:calendar-data/></D:prop>
<C:filter><C:comp-filter name="VCALENDAR"><C:comp-filter name="VEVENT">
<C:time-range start="${utcStamp(from)}" end="${utcStamp(to)}"/>
</C:comp-filter></C:comp-filter></C:filter>
</C:calendar-query>`;
  const res = await report(calHref, auth, query);
  if (res.status >= 400) {
    const busy = appleBusy(res.status);
    if (busy) throw new Error(busy);
    return;
  }
  for (const block of responseBlocks(res.text)) {
    const href = hrefOf(block);
    const sum = icsSummary(block);
    if (!href || sum !== summary) continue;
    const url = caldavUrl(href);
    try {
      await fetch(url, { method: 'DELETE', headers: { Authorization: auth } });
    } catch (_) { /* ما يهم — PUT الجديد يكفي */ }
  }
}

async function putEvent(auth: string, calHref: string, ics: string,
                        eventUid: string): Promise<string> {
  const url = `${calHref.replace(/\/$/, '')}/${eventUid}.ics`;
  const res = await fetch(url, {
    method: 'PUT',
    headers: {
      Authorization: auth,
      'Content-Type': 'text/calendar; charset=utf-8',
    },
    body: ics,
  });
  if (res.status >= 400) {
    throw new Error(appleBusy(res.status) ?? `تعذّرت الكتابة على التقويم (${res.status})`);
  }
  return url;
}

/** يحذف الموعد اللي انكتب (فحص الاتصال فقط — delete_after) */
async function deleteEvent(auth: string, url: string): Promise<void> {
  try {
    await fetch(url, { method: 'DELETE', headers: { Authorization: auth } });
  } catch (_) { /* ما يهم — فحص الاتصال بس */ }
}

Deno.serve(async (req: Request) => {
  const cors = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'content-type,x-relay-token',
    'Access-Control-Allow-Methods': 'POST,OPTIONS',
  };
  if (req.method === 'OPTIONS') return new Response('ok', { headers: cors });
  if (req.method !== 'POST') {
    return new Response(JSON.stringify({ ok: false, error: 'method not allowed' }),
      { status: 405, headers: { ...cors, 'Content-Type': 'application/json' } });
  }
  const expected = Deno.env.get('RELAY_TOKEN') ?? '';
  const given = req.headers.get('x-relay-token') ?? '';
  if (!expected || given !== expected) {
    return new Response(JSON.stringify({ ok: false, error: 'رمز غير صحيح' }),
      { status: 401, headers: { ...cors, 'Content-Type': 'application/json' } });
  }
  try {
    const body = await req.json();
    const appleId = String(body.apple_id ?? '').trim();
    const password = await decryptPassword(String(body.password_b64 ?? ''));
    if (!appleId || !password) throw new Error('بيانات ناقصة');
    const auth = basicAuth(appleId, password);

    const calendars = await getCalendars(auth, appleId);
    if (!calendars.length) throw new Error('لا يوجد تقويم متاح بهذا الحساب');

    const summary = String(body.summary ?? '');
    const start = String(body.start ?? '');
    const minutes = Number(body.duration_minutes ?? 60);
    const description = String(body.description ?? '');
    const deleteAfter = body.delete_after === true || body.delete_after === 'true';
    const eventUid = uid();
    const ics = buildICS(summary, start, minutes, description, eventUid);

    let lastError = 'تعذّرت الكتابة على أي تقويم';
    for (const cal of calendars) {
      try {
        await deleteExisting(auth, cal.href, summary, start);
        const eventUrl = await putEvent(auth, cal.href, ics, eventUid);
        if (deleteAfter) await deleteEvent(auth, eventUrl);
        return new Response(JSON.stringify({ ok: true, calendar: cal.name }),
          { headers: { ...cors, 'Content-Type': 'application/json' } });
      } catch (e) {
        lastError = e instanceof Error ? e.message : String(e);
      }
    }
    return new Response(JSON.stringify({ ok: false, error: lastError }),
      { headers: { ...cors, 'Content-Type': 'application/json' } });
  } catch (e) {
    return new Response(
      JSON.stringify({ ok: false, error: e instanceof Error ? e.message : String(e) }),
      { headers: { ...cors, 'Content-Type': 'application/json' } });
  }
});
