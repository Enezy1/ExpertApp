# ===== gov_notice.py — إنشاء إخطار حضور جلسة خبرة (جهة حكومية) =====
"""
يولّد كتاب "إخطار لحضور جلسة خبرة" الموجّه لجهة حكومية طرف بالدعوى
(المدعي أو المدعى عليه)، ليُطبع ويُوقّع ويُرسل قبل الجلسة القادمة.

يعالج XML لملف Word مباشرة (نفس أسلوب mahdar.py بالضبط) — لا يفتح
docx كامل، عشان نتفادى مشاكل bidi/الخطوط ونحافظ على تنسيق القالب
كما هو حرفيًا.

مصادر البيانات:
  - رقم الدعوى/الواردة من/رقم الخبرة/المرفوعة من/المرفوعة ضد/الخبير/
    المحافظة/القسم  ← نفس مصدر طباعة المحضر (parse_case_info + القاعدة)
  - التاريخ/اليوم/الساعة  ← من الجلسة القادمة (الكرت اللي ضُغط عليه)
  - الجهة الحكومية (السيد الفاضل)  ← الأطراف الحكومية المكتشفة (ui.py)
  - المقر/الدور/المكتب/الجناح  ← إعدادات الخبير (expert_settings.py)

الحقول التي تُترك فاضية عمدًا (تعبّيها السكرتارية يدويًا):
  - التاريخ الأعلى (تبع السكرتارية)
  - الإشارة
"""
import os
import re
import zipfile
import tempfile
from config import GOV_TEMPLATE_PATH
from dates import normalize_date


def fix_dotx(template_path):
    """تحويل .dotx إلى docx مؤقت (نفس منطق mahdar.fix_dotx)"""
    files = {}
    with zipfile.ZipFile(template_path, 'r') as z:
        for name in z.namelist():
            files[name] = z.read(name)
    old = b'wordprocessingml.template.main+xml'
    new = b'wordprocessingml.document.main+xml'
    files['[Content_Types].xml'] = files['[Content_Types].xml'].replace(old, new)
    tmp = tempfile.NamedTemporaryFile(suffix='.docx', delete=False)
    tmp.close()
    with zipfile.ZipFile(tmp.name, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return tmp.name


def make_run(text, size=28):
    """ينشئ run بالنص بتنسيق عربي RTL. size بنصف النقطة (28 = 14pt)."""
    sz = (f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>') if size else ''
    return (
        f'<w:r><w:rPr>'
        f'<w:rFonts w:ascii="Sakkal Majalla" w:hAnsi="Sakkal Majalla" w:cs="Sakkal Majalla"/>'
        f'{sz}<w:i/><w:color w:val="000000"/><w:rtl/>'
        f'</w:rPr><w:t xml:space="preserve">{text}</w:t></w:r>'
    )


def _xml_escape(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def replace_cell(xml, idx, value):
    """يعبّي خلية فاضية بقيمة (يضيف run جديد قبل نهاية أول فقرة)"""
    cells = list(re.finditer(r'<w:tc>(.*?)</w:tc>', xml, re.DOTALL))
    if idx < len(cells):
        old = cells[idx].group(0)
        content = cells[idx].group(1)
        new_content = content.replace('</w:p>', make_run(_xml_escape(value)) + '</w:p>', 1)
        xml = xml.replace(old, f'<w:tc>{new_content}</w:tc>', 1)
    return xml


def overwrite_cell(xml, idx, value):
    """يمسح محتوى الخلية النصّي القديم ويكتب الجديد (للخلايا اللي فيها
    نص افتراضي بالقالب مثل المحافظة/القسم/المقر)"""
    cells = list(re.finditer(r'<w:tc>(.*?)</w:tc>', xml, re.DOTALL))
    if idx < len(cells):
        old = cells[idx].group(0)
        content = cells[idx].group(1)
        new_content = re.sub(r'<w:r\b(?![^>]*<w:tab).*?</w:r>', '', content, flags=re.DOTALL)
        new_content = new_content.replace('</w:p>', make_run(_xml_escape(value)) + '</w:p>', 1)
        xml = xml.replace(old, f'<w:tc>{new_content}</w:tc>', 1)
    return xml


def inject_recipient(xml, value):
    """
    يحقن اسم/أسماء الجهة الحكومية مباشرة بعد الـ '/' في سطر
    'السيد الفاضل /'. لو فيه أكثر من جهة، تُكتب مفصولة بـ ' ، '
    داخل نفس السطر. لو value فاضية، لا يغيّر شيئًا (يبقى السطر فاضي
    ليكتبه الخبير يدويًا).
    """
    if not value:
        return xml
    # نلقى run الـ '/' الذي يلي 'السيد الفاضل' مباشرة، ونحقن بعده
    anchor = re.compile(
        r'(السيد الفاضل\s*</w:t></w:r>'
        r'<w:r[^>]*>(?:(?!</w:r>).)*?<w:t[^>]*>/</w:t></w:r>)',
        re.DOTALL
    )
    m = anchor.search(xml)
    if not m:
        return xml
    point = m.end()
    injected = (
        f'<w:r><w:rPr>'
        f'<w:rFonts w:ascii="Sakkal Majalla" w:hAnsi="Sakkal Majalla" w:cs="Sakkal Majalla"/>'
        f'<w:b w:val="0"/><w:i/><w:color w:val="auto"/>'
        f'<w:sz w:val="40"/><w:szCs w:val="40"/><w:rtl/>'
        f'</w:rPr><w:t xml:space="preserve"> {_xml_escape(value)}</w:t></w:r>'
    )
    return xml[:point] + injected + xml[point:]


def fill_gov_notice(output_path, data):
    """
    يعبّي إخطار الحكومة ويحفظه في output_path.

    مفاتيح data المتوقّعة (كلها اختيارية — الفاضي يبقى فاضي):
      رقم_الدعوى، الواردة_من، رقم_الخبرة، المرفوعة_من، المرفوعة_ضد،
      الخبير، المحافظة، القسم، التاريخ، اليوم، الساعة،
      المقر، الدور، المكتب، الجناح، الجهة (اسم/أسماء الجهة الحكومية)
    """
    fixed = fix_dotx(GOV_TEMPLATE_PATH)
    files = {}
    with zipfile.ZipFile(fixed, 'r') as z:
        for name in z.namelist():
            files[name] = z.read(name)
    os.unlink(fixed)

    d = files['word/document.xml'].decode('utf-8')

    # === السيد الفاضل / (الجهة الحكومية) ===
    d = inject_recipient(d, data.get('الجهة', ''))

    # === صف: رقم الدعوى / الواردة من / رقم الخبرة (خلايا القيم 2،4،6) ===
    d = replace_cell(d, 2, data.get('رقم_الدعوى', ''))
    d = replace_cell(d, 4, data.get('الواردة_من', ''))
    d = replace_cell(d, 6, data.get('رقم_الخبرة', ''))

    # === المرفوعة من (8) — فيها نص تجريبي 'انتا' بالقالب نمسحه ===
    d = overwrite_cell(d, 8, data.get('المرفوعة_من', ''))

    # === المرفوعة ضد (10) ===
    d = replace_cell(d, 10, data.get('المرفوعة_ضد', ''))

    # === بيانات الجلسة: الخبير (13) ===
    d = replace_cell(d, 13, data.get('الخبير', ''))

    # === المحافظة (15) والقسم (17) — فيهما نص افتراضي بالقالب ===
    if data.get('المحافظة'):
        d = overwrite_cell(d, 15, data.get('المحافظة', ''))
    if data.get('القسم'):
        d = overwrite_cell(d, 17, data.get('القسم', ''))

    # === التاريخ (19) / اليوم (21) / الساعة (23) ===
    date_val = normalize_date(data.get('التاريخ', '')) if data.get('التاريخ') else ''
    d = replace_cell(d, 19, date_val)
    d = replace_cell(d, 21, data.get('اليوم', ''))
    d = replace_cell(d, 23, data.get('الساعة', ''))

    # === المقر (25) / الدور (27) / المكتب (29) / الجناح (35) ===
    if data.get('المقر'):
        d = overwrite_cell(d, 25, data.get('المقر', ''))
    d = replace_cell(d, 27, data.get('الدور', ''))
    d = replace_cell(d, 29, data.get('المكتب', ''))
    d = replace_cell(d, 35, data.get('الجناح', ''))

    files['word/document.xml'] = d.encode('utf-8')

    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return output_path
