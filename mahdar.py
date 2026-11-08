# ===== mahdar.py — إنشاء محضر الجلسة =====
import os
import re
import zipfile
import tempfile
from config import TEMPLATE_PATH
from dates import normalize_date


def fix_dotx(template_path):
    """تحويل .dotx إلى docx مؤقت"""
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


def make_run(text):
    """ينشئ run بالنص مع تنسيق عربي"""
    return (
        f'<w:r><w:rPr>'
        f'<w:rFonts w:asciiTheme="majorBidi" w:hAnsiTheme="majorBidi" w:cstheme="majorBidi"/>'
        f'<w:b/><w:bCs/><w:color w:val="000000"/><w:rtl/>'
        f'</w:rPr><w:t xml:space="preserve">{text}</w:t></w:r>'
    )


def replace_cell(xml, idx, value, rtl_para=False):
    """تعبية خلية فاضية بالرقم"""
    cells = list(re.finditer(r'<w:tc>(.*?)</w:tc>', xml, re.DOTALL))
    if idx < len(cells):
        old = cells[idx].group(0)
        content = cells[idx].group(1)
        if rtl_para:
            content = content.replace('<w:pPr>', '<w:pPr><w:bidi/>', 1)
        new_content = content.replace('</w:p>', make_run(value) + '</w:p>', 1)
        xml = xml.replace(old, f'<w:tc>{new_content}</w:tc>', 1)
    return xml


def overwrite_cell(xml, idx, value):
    """يمسح محتوى الخلية ويكتب الجديد"""
    cells = list(re.finditer(r'<w:tc>(.*?)</w:tc>', xml, re.DOTALL))
    if idx < len(cells):
        old = cells[idx].group(0)
        content = cells[idx].group(1)
        new_content = re.sub(r'<w:r>.*?</w:r>', '', content, flags=re.DOTALL)
        new_content = new_content.replace('</w:p>', make_run(value) + '</w:p>', 1)
        xml = xml.replace(old, f'<w:tc>{new_content}</w:tc>', 1)
    return xml


def append_after_text(xml, anchor_text, value):
    """
    يضيف نصاً مباشرة بعد أول ظهور لـ anchor_text داخل القالب (نص ثابت
    خارج الجداول، مثل 'وقد حضر في الموعد المحدد كل من:' أو
    'وبوشرت المهمة المطلوبة كما يلي:'). يبحث عن run الذي يحتوي
    anchor_text، ثم يحقن run جديد بعده مباشرة بنفس التنسيق (Bold, RTL).
    لا يغيّر أي شيء آخر بالمستند إن لم يجد anchor_text.
    """
    pattern = re.compile(
        r'(<w:r[^>]*>(?:(?!</w:r>).)*?<w:t[^>]*>' + re.escape(anchor_text) + r'</w:t></w:r>)',
        re.DOTALL
    )
    match = pattern.search(xml)
    if not match:
        return xml
    insertion_point = match.end()
    new_run = (
        f'<w:r><w:rPr>'
        f'<w:rFonts w:asciiTheme="majorBidi" w:hAnsiTheme="majorBidi" w:cstheme="majorBidi"/>'
        f'<w:sz w:val="28"/><w:szCs w:val="28"/><w:rtl/><w:lang w:bidi="ar-KW"/>'
        f'</w:rPr><w:t xml:space="preserve"> {value}</w:t></w:r>'
    )
    return xml[:insertion_point] + new_run + xml[insertion_point:]


def fill_mahdar(output_path, data):
    """تعبية المحضر وحفظه"""
    fixed = fix_dotx(TEMPLATE_PATH)
    files = {}
    with zipfile.ZipFile(fixed, 'r') as z:
        for name in z.namelist():
            files[name] = z.read(name)
    os.unlink(fixed)

    # === الهيدر ===
    h = files['word/header2.xml'].decode('utf-8')
    h = replace_cell(h, 1, data.get('رقم_المحضر', ''))
    h = replace_cell(h, 3, data.get('اليوم', ''))

    # نطبّع التاريخ فقط (يتعرف على الصيغة تلقائياً بغض النظر عن مصدره:
    # سنة-أول بالسلاش من جلسات السيرفر، أو يوم-أول جاهز من محضر أول
    # جلسة)، ويُكتب بالخلية كما هو — بدون أي عكس إضافي، لأنه لا يوجد
    # فعلياً أي حاجة لعكس bidi بهذه الخلية (تأكدنا بالتجربة الفعلية)
    date_val = normalize_date(data.get('التاريخ', ''))
    h = replace_cell(h, 5, date_val, rtl_para=True)
    h = replace_cell(h, 7, data.get('رقم_الخبرة', ''))
    files['word/header2.xml'] = h.encode('utf-8')

    # === الجسم ===
    d = files['word/document.xml'].decode('utf-8')

    # الساعة
    d = replace_cell(d, 1, data.get('الساعة', ''))

    # بمقر
    gov = data.get('المحافظة', 'العاصمة')
    d = overwrite_cell(d, 3, f'إدارة شئون خبراء {gov}')

    # رقم الدعوى
    case_num = data.get('رقم_الدعوى', '')
    if case_num:
        d = replace_cell(d, 5, case_num)

    # الواردة من
    d = replace_cell(d, 7, data.get('الواردة_من', ''))

    # المرفوعة من
    d = replace_cell(d, 9, data.get('المرفوعة_من', ''))

    # المرفوعة ضد
    d = replace_cell(d, 11, data.get('المرفوعة_ضد', ''))

    # بحضور الخبير — الأسماء في سطر واحد بفاصلة
    expert_text = data.get('الخبير', '')
    experts_list = [e.strip() for e in expert_text.split('    ') if e.strip()]
    if len(experts_list) > 1:
        expert_text = '  ،  '.join(experts_list)
    d = replace_cell(d, 13, expert_text)

    # المحافظة والقسم
    if data.get('المحافظة'):
        d = overwrite_cell(d, 15, data.get('المحافظة', ''))
    if data.get('القسم'):
        d = overwrite_cell(d, 17, data.get('القسم', ''))

    # نص الحضور (مثل 'لم يحضر أحد' في محضر أول جلسة) — يُضاف بعد
    # 'وقد حضر في الموعد المحدد كل من:' الثابتة بالقالب
    if data.get('نص_الحضور'):
        d = append_after_text(d, 'وقد حضر في الموعد المحدد كل من:', data['نص_الحضور'])

    # الجملة الديناميكية لمحضر أول جلسة — تُضاف بعد
    # 'وبوشرت المهمة المطلوبة كما يلي:' الثابتة بالقالب
    if data.get('نص_المهمة'):
        d = append_after_text(d, 'وبوشرت المهمة المطلوبة كما يلي:', data['نص_المهمة'])

    files['word/document.xml'] = d.encode('utf-8')

    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return output_path