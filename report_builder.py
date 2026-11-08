import io, re, base64
from xml.sax.saxutils import escape
from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import qn

FONT = "Sakkal Majalla"
LINE_Y = 1600000  # header rule, EMU from page top (just under the department name)
NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
      'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
      'xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing" '
      'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
      'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" mc:Ignorable="w14 wp14"')
NSW = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

IMAGES = {}  # filled by the caller: {"emblem": bytes, "badge": bytes}


# ---------------------------------------------------------------- low-level xml helpers
def rpr(b=False, u=False, sz=32):
    return ('<w:rPr><w:rFonts w:ascii="%s" w:hAnsi="%s" w:eastAsia="%s" w:cs="%s"/>%s%s'
            '<w:sz w:val="%d"/><w:szCs w:val="%d"/>%s<w:rtl/></w:rPr>') % (
        FONT, FONT, FONT, FONT, '<w:b/><w:bCs/>' if b else '',
        '', sz, sz, '<w:u w:val="single"/>' if u else '')


def runs(text, b=False, u=False, sz=32):
    """Inline markup: **bold**   __underline__ (can be combined). Returns run xml."""
    out = []
    for tok in re.split(r'(\*\*|__)', text):
        if tok == '**':
            b = not b
        elif tok == '__':
            u = not u
        elif tok:
            out.append('<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % (rpr(b, u, sz), escape(tok)))
    return ''.join(out)


def para(text='', jc='both', b=False, u=False, sz=32, line=276, keep_next=False,
         page_break_before=False, num=None, before=None, after=None, extra=''):
    ppr = ''
    if keep_next: ppr += '<w:keepNext/>'
    if page_break_before: ppr += '<w:pageBreakBefore/>'
    if num: ppr += '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="%d"/></w:numPr>' % num
    sp = '<w:spacing'
    if before is not None: sp += ' w:before="%d"' % before
    if after is not None: sp += ' w:after="%d"' % after
    if line: sp += ' w:line="%d" w:lineRule="auto"' % line
    sp += '/>'
    ppr += sp + extra
    if jc: ppr += '<w:jc w:val="%s"/>' % jc
    ppr += rpr(b, u, sz).replace('<w:rtl/>', '')  # paragraph-mark props (size of list numbers)
    return '<w:p %s><w:pPr>%s</w:pPr>%s</w:p>' % (NSW, ppr, runs(text, b, u, sz))


def cell(content_xml, w, fill=None, span=1, valign='center', borders=''):
    tcpr = '<w:tcW w:w="%d" w:type="dxa"/>' % w
    if span > 1: tcpr += '<w:gridSpan w:val="%d"/>' % span
    if borders: tcpr += borders
    if fill: tcpr += '<w:shd w:val="clear" w:color="auto" w:fill="%s"/>' % fill
    tcpr += '<w:vAlign w:val="%s"/>' % valign
    return '<w:tc><w:tcPr>%s</w:tcPr>%s</w:tc>' % (tcpr, content_xml)


def strip_ns(x):
    return x.replace(' ' + NSW, '')


# ---------------------------------------------------------------- numbering definitions
def numbering_xml():
    # abstract 1: bullet (Symbol), 2: decimal "%1-" , 3: decimal "%1)"
    return ('<w:numbering %s>'
            '<w:abstractNum w:abstractNumId="1"><w:multiLevelType w:val="hybridMultilevel"/>'
            '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="&#xF0B7;"/><w:lvlJc w:val="left"/>'
            '<w:pPr><w:ind w:left="360" w:hanging="360"/></w:pPr>'
            '<w:rPr><w:rFonts w:ascii="Symbol" w:hAnsi="Symbol" w:cs="Symbol" w:hint="default"/></w:rPr></w:lvl></w:abstractNum>'
            '<w:abstractNum w:abstractNumId="2"><w:multiLevelType w:val="hybridMultilevel"/>'
            '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%%1-"/><w:lvlJc w:val="left"/>'
            '<w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl></w:abstractNum>'
            '<w:abstractNum w:abstractNumId="3"><w:multiLevelType w:val="hybridMultilevel"/>'
            '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%%1)"/><w:lvlJc w:val="left"/>'
            '<w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl></w:abstractNum>'
            '<w:num w:numId="1"><w:abstractNumId w:val="1"/></w:num>'
            '</w:numbering>') % NSW


# ---------------------------------------------------------------- header (letterhead)
def _pic(rid, name, did, cx, cy, hrel, hoff, vrel, voff, z):
    return ('<w:r><w:rPr><w:noProof/></w:rPr><w:drawing><wp:anchor distT="0" distB="0" distL="114300" distR="114300" '
            'simplePos="0" relativeHeight="%d" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">'
            '<wp:simplePos x="0" y="0"/><wp:positionH relativeFrom="%s"><wp:posOffset>%d</wp:posOffset></wp:positionH>'
            '<wp:positionV relativeFrom="%s"><wp:posOffset>%d</wp:posOffset></wp:positionV>'
            '<wp:extent cx="%d" cy="%d"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>'
            '<wp:docPr id="%d" name="%s"/><wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
            '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>'
            '<pic:nvPicPr><pic:cNvPr id="0" name="%s"/><pic:cNvPicPr/></pic:nvPicPr>'
            '<pic:blipFill><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
            '</pic:pic></a:graphicData></a:graphic></wp:anchor></w:drawing></w:r>') % (
        z, hrel, hoff, vrel, voff, cx, cy, did, name, name, rid, cx, cy)


def _textbox(text, did, hoff, voff, z, w=961390):
    return ('<w:r><w:rPr><w:noProof/></w:rPr><w:drawing><wp:anchor distT="45720" distB="45720" distL="114300" distR="114300" '
            'simplePos="0" relativeHeight="%d" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">'
            '<wp:simplePos x="0" y="0"/><wp:positionH relativeFrom="margin"><wp:posOffset>%d</wp:posOffset></wp:positionH>'
            '<wp:positionV relativeFrom="page"><wp:posOffset>%d</wp:posOffset></wp:positionV>'
            '<wp:extent cx="%d" cy="335280"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>'
            '<wp:docPr id="%d" name="Text Box %d"/><wp:cNvGraphicFramePr/>'
            '<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"><wps:wsp>'
            '<wps:cNvSpPr txBox="1"/><wps:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="335280"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></wps:spPr>'
            '<wps:txbx><w:txbxContent><w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:rFonts w:ascii="Andalus" w:hAnsi="Andalus" w:cs="Andalus" w:hint="cs"/>'
            '<w:b/><w:bCs/><w:sz w:val="28"/><w:szCs w:val="28"/><w:rtl/></w:rPr><w:t>%s</w:t></w:r></w:p></w:txbxContent></wps:txbx>'
            '<wps:bodyPr rot="0" vert="horz" wrap="square" lIns="91440" tIns="45720" rIns="91440" bIns="45720" anchor="t" anchorCtr="0"><a:noAutofit/></wps:bodyPr>'
            '</wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing></w:r>') % (z, hoff, voff, w, did, did, w, escape(text))


def _line(did, z):
    return ('<w:r><w:rPr><w:noProof/></w:rPr><w:drawing><wp:anchor distT="0" distB="0" distL="114300" distR="114300" '
            'simplePos="0" relativeHeight="%d" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">'
            '<wp:simplePos x="0" y="0"/><wp:positionH relativeFrom="column"><wp:posOffset>-31750</wp:posOffset></wp:positionH>'
            '<wp:positionV relativeFrom="page"><wp:posOffset>%d</wp:posOffset></wp:positionV>'
            '<wp:extent cx="6372000" cy="0"/><wp:effectExtent l="19050" t="19050" r="10160" b="19050"/><wp:wrapNone/>'
            '<wp:docPr id="%d" name="Straight Connector %d"/><wp:cNvGraphicFramePr/>'
            '<a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"><wps:wsp><wps:cNvCnPr/>'
            '<wps:spPr><a:xfrm flipH="1"><a:off x="0" y="0"/><a:ext cx="6372000" cy="0"/></a:xfrm><a:prstGeom prst="line"><a:avLst/></a:prstGeom>'
            '<a:ln w="28575"><a:solidFill><a:schemeClr val="tx1"/></a:solidFill></a:ln></wps:spPr>'
            '<wps:style><a:lnRef idx="1"><a:schemeClr val="dk1"/></a:lnRef><a:fillRef idx="0"><a:schemeClr val="dk1"/></a:fillRef>'
            '<a:effectRef idx="0"><a:schemeClr val="dk1"/></a:effectRef><a:fontRef idx="minor"><a:schemeClr val="tx1"/></a:fontRef></wps:style>'
            '<wps:bodyPr/></wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing></w:r>') % (z, LINE_Y, did, did)


def header_xml(rid_emblem, rid_badge, line2="الإدارة العامة للخبراء"):
    andalus = '<w:rFonts w:ascii="Andalus" w:hAnsi="Andalus" w:cs="Andalus"/><w:b/><w:bCs/>'
    p1 = ('<w:p><w:pPr><w:pStyle w:val="Header"/><w:jc w:val="center"/></w:pPr>%s%s</w:p>' % (
        _pic(rid_emblem, "Emblem", 55, 869315, 974090, "margin", 2599200, "page", 195636, 251658242),
        _pic(rid_badge, "Badge", 57, 2156460, 829310, "column", 4121150, "paragraph", -97378, 251658240)))
    p2 = ('<w:p><w:pPr><w:jc w:val="center"/><w:rPr>%s<w:szCs w:val="32"/></w:rPr></w:pPr>'
          '<w:r><w:rPr>%s<w:szCs w:val="32"/><w:rtl/></w:rPr><w:t>وزارة العدل</w:t></w:r></w:p>') % (andalus, andalus)
    ind = '<w:ind w:left="-319" w:right="-142"/>'
    p3 = '<w:p><w:pPr>%s<w:jc w:val="center"/></w:pPr>%s</w:p>' % (ind, _textbox("وزارة العدل", 217, 2527935, 1017961, 251658243))
    p4 = '<w:p><w:pPr>%s<w:jc w:val="center"/></w:pPr>%s</w:p>' % (ind, _textbox(line2, 218, 2058630, 1209600, 251660292, 1900000))
    p5 = '<w:p><w:pPr>%s</w:pPr>%s</w:p>' % (ind, _line(58, 251658244))
    return '<w:hdr %s>%s%s%s%s%s</w:hdr>' % (NS, p1, p2, p3, p4, p5)


def footer_xml():
    r = '<w:rPr><w:sz w:val="24"/><w:szCs w:val="24"/><w:rtl/></w:rPr>'
    fld = ('<w:r>%s<w:fldChar w:fldCharType="begin"/></w:r><w:r>%s<w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
           '<w:r>%s<w:fldChar w:fldCharType="separate"/></w:r><w:r>%s<w:t>1</w:t></w:r><w:r>%s<w:fldChar w:fldCharType="end"/></w:r>') % (r, r, r, r, r)
    return ('<w:ftr %s><w:p><w:pPr><w:pStyle w:val="Footer"/>'
            '<w:pBdr><w:top w:val="single" w:sz="24" w:space="4" w:color="000000"/></w:pBdr><w:jc w:val="center"/></w:pPr>%s</w:p></w:ftr>') % (NSW, fld)


# ---------------------------------------------------------------- the report
class Report:
    def __init__(self, header_line2="الإدارة العامة للخبراء"):
        self.doc = Document()
        self.parts = []
        self.nextnum = 2
        self.extra_nums = []
        self._setup(header_line2)

    # ---- page / styles / header / footer
    def _setup(self, line2):
        d = self.doc
        st = d.styles.element
        dd = st.find(qn('w:docDefaults'))
        if dd is not None: st.remove(dd)
        dd = parse_xml('<w:docDefaults %s><w:rPrDefault><w:rPr><w:rFonts w:ascii="%s" w:eastAsia="%s" w:hAnsi="%s" w:cs="%s"/>'
                       '<w:sz w:val="32"/><w:szCs w:val="32"/><w:lang w:val="en-US" w:eastAsia="en-US" w:bidi="ar-KW"/></w:rPr></w:rPrDefault>'
                       '<w:pPrDefault/></w:docDefaults>' % (NSW, FONT, FONT, FONT, FONT))
        st.insert(0, dd)
        normal = d.styles['Normal'].element
        ppr = normal.find(qn('w:pPr'))
        if ppr is None:
            ppr = parse_xml('<w:pPr %s/>' % NSW); normal.append(ppr)
        for ch in list(ppr): ppr.remove(ch)
        ppr.append(parse_xml('<w:bidi %s/>' % NSW))
        # numbering
        npart = d.part.numbering_part
        npart._element = parse_xml(numbering_xml())
        self.numbering = npart
        # section
        sec = d.sections[0]
        sec.header.is_linked_to_previous = False
        sec.footer.is_linked_to_previous = False
        hp = sec.header.part
        rid_e = hp.get_or_add_image(io.BytesIO(IMAGES["emblem"]))[0]
        rid_b = hp.get_or_add_image(io.BytesIO(IMAGES["badge"]))[0]
        hp._element = parse_xml(header_xml(rid_e, rid_b, line2))
        sec.footer.part._element = parse_xml(footer_xml())
        sp = sec._sectPr
        for tag in ('w:pgSz', 'w:pgMar', 'w:cols', 'w:docGrid', 'w:bidi', 'w:rtlGutter'):
            for e in sp.findall(qn(tag)): sp.remove(e)
        for x in ('<w:pgSz %s w:w="11906" w:h="16838"/>', '<w:pgMar %s w:top="1440" w:right="1080" w:bottom="1560" w:left="1080" w:header="680" w:footer="737" w:gutter="0"/>',
                  '<w:cols %s w:space="720"/>', '<w:bidi %s/>', '<w:rtlGutter %s/>', '<w:docGrid %s w:linePitch="272"/>'):
            sp.append(parse_xml(x % NSW))
        cp = d.core_properties
        cp.author = ''; cp.last_modified_by = ''; cp.title = ''; cp.comments = ''

    # ---- numbering lists
    def _new_list(self, abstract):
        n = self.nextnum; self.nextnum += 1
        self.extra_nums.append('<w:num %s w:numId="%d"><w:abstractNumId w:val="%d"/>'
                               '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride></w:num>' % (NSW, n, abstract))
        return n

    # ---- blocks
    def add(self, xml): self.parts.append(xml)
    def blank(self, keep_next=False): self.add(para('', jc='both', keep_next=keep_next))

    def info_table(self, date, number, case_no, source, plaintiffs, defendants, experts,
                   plaintiff_label="المرفوعة من", defendant_label="المرفوعة ضد", experts_label="الخبــــــــير",
                   governorate="العاصمة", department="قضايا الكهرباء والكمبيوتر"):
        """First table. plaintiffs/defendants/experts: list of strings (several => numbered '1-' list)."""
        W = [1562, 4392, 1275, 2694]
        def c(text, w, label=False, span=1):
            return cell(para(text, jc='center', b=label, line=None, before=16), w, fill='F2F2F2' if label else None, span=span)
        def multi(items, label):
            if len(items) == 1:
                body = para(items[0], jc='center', line=None, before=16)
            else:
                n = self._new_list(2)
                body = ''.join(para(i, jc='center', line=None, before=16, num=n) for i in items)
            return ('<w:tr><w:trPr><w:trHeight w:val="20"/></w:trPr>%s%s</w:tr>') % (
                c(label, W[0], True), cell(body, sum(W[1:]), span=3))
        rows = ['<w:tr><w:trPr><w:trHeight w:val="20"/></w:trPr>%s%s%s%s</w:tr>' % (
                    c("تاريخ التقرير", W[0], True), c(date, W[1]), c("رقم الخبرة", W[2], True), c(number, W[3])),
                '<w:tr><w:trPr><w:trHeight w:val="20"/></w:trPr>%s%s%s%s</w:tr>' % (
                    c("رقم الدعوى", W[0], True), c(case_no, W[1]), c("الواردة من", W[2], True), c(source, W[3])),
                multi(plaintiffs, plaintiff_label), multi(defendants, defendant_label), multi(experts, experts_label),
                '<w:tr><w:trPr><w:trHeight w:val="20"/></w:trPr>%s%s%s%s</w:tr>' % (
                    c("المحـافـظـة", W[0], True), c(governorate, W[1]), c("القســــم", W[2], True), c(department, W[3]))]
        tbl = ('<w:tbl %s><w:tblPr><w:bidiVisual/><w:tblW w:w="9923" w:type="dxa"/><w:jc w:val="center"/>'
               '<w:tblBorders><w:top w:val="thinThickSmallGap" w:sz="12" w:space="0" w:color="auto"/>'
               '<w:left w:val="thickThinSmallGap" w:sz="12" w:space="0" w:color="auto"/>'
               '<w:bottom w:val="thickThinSmallGap" w:sz="12" w:space="0" w:color="auto"/>'
               '<w:right w:val="thinThickSmallGap" w:sz="12" w:space="0" w:color="auto"/>'
               '<w:insideH w:val="single" w:sz="8" w:space="0" w:color="auto"/><w:insideV w:val="single" w:sz="8" w:space="0" w:color="auto"/></w:tblBorders>'
               '<w:tblLayout w:type="fixed"/><w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="1" w:lastColumn="0" w:noHBand="0" w:noVBand="1"/></w:tblPr>'
               '<w:tblGrid>%s</w:tblGrid>%s</w:tbl>') % (
            NSW, ''.join('<w:gridCol w:w="%d"/>' % w for w in W), ''.join(strip_ns(r) for r in rows))
        self.add(tbl)
        self.blank()

    def title(self, text="التـقـرير"):
        self.add(para(text, jc='center', b=True, u=True, sz=36))

    def heading(self, text, page_break_before=False):
        """Main headings: الموضوع: / المأمورية: / الإجراءات: / المعاينة: / البحث ورأي الخبرة: / النتيجة: / المرفقات:"""
        self.add(para(text, jc=None, b=True, u=True, sz=36, keep_next=True, page_break_before=page_break_before))

    def text(self, t, jc='both', b=False, u=False, blank_after=False):
        self.add(para(t, jc=jc, b=b, u=u))
        if blank_after: self.blank()

    def subheading(self, t):          # e.g. "أ) التزام المدعيين بسداد الثمن:"
        self.add(para(t, jc='both', b=True, u=True, keep_next=True))

    def conclusion(self, t):          # "مما سبق ترى الخبرة ..." (centered, bold + underline)
        self.add(para(t, jc='center', b=True, u=True))

    def box(self, t):                 # "أولاً: ..." section box (thick top/bottom rules)
        none = '<w:%s w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        brd = ('<w:tblBorders><w:top w:val="single" w:sz="18" w:space="0" w:color="auto"/>' + none % 'left' +
               '<w:bottom w:val="single" w:sz="18" w:space="0" w:color="auto"/>' + none % 'right' + none % 'insideH' + none % 'insideV' + '</w:tblBorders>')
        self.add('<w:tbl %s><w:tblPr><w:bidiVisual/><w:tblW w:w="9736" w:type="dxa"/>%s<w:tblLayout w:type="fixed"/></w:tblPr>'
                 '<w:tblGrid><w:gridCol w:w="9736"/></w:tblGrid><w:tr><w:trPr><w:cantSplit/></w:trPr>%s</w:tr></w:tbl>' % (
                     NSW, brd, strip_ns(cell(para(t, jc='both', b=True, keep_next=True), 9736, valign='top'))))
        self.blank(keep_next=True)

    def bullets(self, items, b=False):
        for i in items:
            self.add(para(i, jc='both', num=1, b=b))

    def numbered(self, items, sz=32):
        n = self._new_list(3)
        for i in items:
            self.add(para(i, jc=None, num=n, sz=sz, line=None, before=0, after=0))

    def data_table(self, headers, rows, widths, bold_rows=(), span_rows=()):
        """headers: list[str]; rows: list[list[str]]; widths: dxa list (sum ~9736).
        span_rows: indexes of rows (in `rows`) that are a single full-width group title (row = [text]). bold_rows: indexes shown bold."""
        def tc(t, w, b=False, fill=None, span=1):
            return cell('<w:p><w:pPr><w:spacing w:line="264" w:lineRule="auto"/><w:jc w:val="center"/></w:pPr>%s</w:p>' % runs(t, b=b, sz=28),
                        w, fill=fill, span=span)
        def tr(cells): return '<w:tr><w:trPr><w:cantSplit/></w:trPr>%s</w:tr>' % ''.join(cells)
        out = [tr([tc(h, w, True, 'F2F2F2') for h, w in zip(headers, widths)])]
        for i, r in enumerate(rows):
            if i in span_rows:
                out.append(tr([tc(r[0], sum(widths), True, 'F2F2F2', span=len(widths))]))
            else:
                out.append(tr([tc(t, w, i in bold_rows) for t, w in zip(r, widths)]))
        self.add(('<w:tbl %s><w:tblPr><w:bidiVisual/><w:tblW w:w="%d" w:type="dxa"/><w:jc w:val="center"/>'
                  '<w:tblBorders><w:top w:val="single" w:sz="6" w:space="0" w:color="auto"/><w:left w:val="single" w:sz="6" w:space="0" w:color="auto"/>'
                  '<w:bottom w:val="single" w:sz="6" w:space="0" w:color="auto"/><w:right w:val="single" w:sz="6" w:space="0" w:color="auto"/>'
                  '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="auto"/><w:insideV w:val="single" w:sz="4" w:space="0" w:color="auto"/></w:tblBorders>'
                  '<w:tblLayout w:type="fixed"/><w:tblCellMar><w:top w:w="40" w:type="dxa"/><w:left w:w="80" w:type="dxa"/>'
                  '<w:bottom w:w="40" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar></w:tblPr>'
                  '<w:tblGrid>%s</w:tblGrid>%s</w:tbl>') % (
            NSW, sum(widths), ''.join('<w:gridCol w:w="%d"/>' % w for w in widths), ''.join(strip_ns(x) for x in out)))
        self.blank()

    def closing(self):
        self.add(para("“والله ولــــي التــــوفيــق “", jc='center'))

    def signature(self, experts):
        """experts: list of (title, name) e.g. ("الخبير المهندس","محمد عبدالله العنزي"); 1 => placed in the LAST (left-most) cell,
        2-3 => in listed order (first = right-most cell)."""
        W = [3726, 2294, 3513]
        n = len(experts)
        slots = [None, None, None]
        if n == 1: slots[2] = experts[0]
        else:
            for i, e in enumerate(experts[:3]): slots[i] = e
        def tc(t, w): return cell(para(t, jc='center', line=276), w, valign='top')
        r1 = '<w:tr><w:trPr><w:trHeight w:val="236"/></w:trPr>%s</w:tr>' % ''.join(tc(s[0] if s else '', w) for s, w in zip(slots, W))
        r2 = '<w:tr><w:trPr><w:trHeight w:val="594"/></w:trPr>%s</w:tr>' % ''.join(tc(s[1] if s else '', w) for s, w in zip(slots, W))
        none = ''.join('<w:%s w:val="none" w:sz="0" w:space="0" w:color="auto"/>' % k for k in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'))
        self.add('<w:tbl %s><w:tblPr><w:bidiVisual/><w:tblW w:w="9533" w:type="dxa"/><w:tblBorders>%s</w:tblBorders><w:tblLayout w:type="fixed"/></w:tblPr>'
                 '<w:tblGrid>%s</w:tblGrid>%s%s</w:tbl>' % (NSW, none, ''.join('<w:gridCol w:w="%d"/>' % w for w in W), strip_ns(r1), strip_ns(r2)))
        self.blank()

    # ---- output
    def save(self, path):
        body = self.doc.element.body
        sect = body.find(qn('w:sectPr'))
        for ch in list(body):
            if ch is not sect: body.remove(ch)
        for x in self.parts:
            sect.addprevious(parse_xml(x))
        if self.extra_nums:
            root = self.numbering._element
            for x in self.extra_nums: root.append(parse_xml(x))
        self.doc.save(path)
        return path


def load_images(emblem_b64, badge_b64):
    IMAGES["emblem"] = base64.b64decode(emblem_b64)
    IMAGES["badge"] = base64.b64decode(badge_b64)
