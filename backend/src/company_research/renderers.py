from html import escape
from pathlib import Path
from .schemas import ReportDocument


def pdf_fonts():
    """Regular and bold CJK fonts for the PDF body; falls back to the built-in CID font."""
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    from .charts import pdf_font

    regular = pdf_font()
    if regular != 'ChartCJK':
        return regular, regular
    if 'ChartCJKBold' not in pdfmetrics.getRegisteredFontNames():
        bold = next((p for p in [Path('C:/Windows/Fonts/msyhbd.ttc'), Path('C:/Windows/Fonts/simhei.ttf')] if p.is_file()), None)
        try:
            options = {'subfontIndex': 0} if bold and bold.suffix == '.ttc' else {}
            pdfmetrics.registerFont(TTFont('ChartCJKBold', str(bold), **options))
        except Exception:
            return regular, regular
    addMapping('ChartCJK', 0, 0, 'ChartCJK')
    addMapping('ChartCJK', 1, 0, 'ChartCJKBold')
    return regular, 'ChartCJKBold'


def export_pdf(report: ReportDocument, path: Path):
    """ReportLab multi-pass TOC records final page positions; no guessed pages."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.platypus.tableofcontents import TableOfContents

    from .charts import to_drawing
    from .presentation import lead, present
    from .reports import NUMERIC

    view = present(report)
    regular, bold = pdf_fonts()
    brand = colors.HexColor('#8C1D18')
    muted = colors.HexColor('#666666')
    body = ParagraphStyle('body', fontName=regular, fontSize=10, leading=17, spaceAfter=7, wordWrap='CJK', alignment=4)
    small = ParagraphStyle('small', parent=body, fontSize=7.5, leading=10, spaceAfter=6, textColor=muted, alignment=0)
    cap = ParagraphStyle('cap', parent=body, fontName=bold, fontSize=9, leading=12, spaceAfter=2, alignment=0, keepWithNext=True)
    cell = ParagraphStyle('cell', parent=body, fontSize=8, leading=10.5, spaceAfter=0, alignment=0)
    num = ParagraphStyle('num', parent=cell, alignment=2)
    title = ParagraphStyle('title', parent=body, fontName=bold, fontSize=20, leading=28, textColor=brand, spaceAfter=10, alignment=0)
    h1 = ParagraphStyle('h1', parent=body, fontName=bold, fontSize=15, leading=22, spaceBefore=16, spaceAfter=8, textColor=brand, keepWithNext=True, alignment=0)
    h2 = ParagraphStyle('h2', parent=h1, fontSize=12, leading=18, spaceBefore=10, textColor=colors.HexColor('#222222'))
    h3 = ParagraphStyle('h3', parent=h2, fontSize=10.5, leading=16, spaceBefore=6)

    class ReportDoc(BaseDocTemplate):
        def afterFlowable(self, flowable):
            if hasattr(flowable, 'toc_entry'):
                level, text, anchor = flowable.toc_entry
                self.canv.bookmarkPage(anchor)
                self.notify('TOCEntry', (level, text, self.page, anchor))

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = ReportDoc(str(path), pagesize=A4, leftMargin=50, rightMargin=50, topMargin=52, bottomMargin=48, title=view.title)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='normal')

    def page(canvas, document):
        canvas.saveState()
        canvas.setStrokeColor(brand)
        canvas.setLineWidth(1.2)
        canvas.line(50, A4[1] - 38, A4[0] - 50, A4[1] - 38)
        canvas.setFont(regular, 8)
        canvas.setFillColor(muted)
        canvas.drawString(50, A4[1] - 32, view.title)
        canvas.drawRightString(A4[0] - 50, A4[1] - 32, view.subtitle)
        canvas.drawRightString(A4[0] - 50, 28, str(document.page))
        canvas.restoreState()

    doc.addPageTemplates(PageTemplate(id='pages', frames=[frame], onPage=page))

    def para(text):
        head, rest = lead(text)
        return Paragraph((f'<b>{escape(head)}</b>' if head else '') + escape(rest), body)

    def data_table(t, numbered=True):
        rows = [[Paragraph(f'<b>{escape(c)}</b>', cell) for c in t.columns]]
        style = [
            ('LINEABOVE', (0, 0), (-1, 0), 1.4, brand),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F3F0EF')),
            ('LINEBELOW', (0, 0), (-1, -1), 0.3, colors.HexColor('#D9D9D9')),
            ('LINEBELOW', (0, -1), (-1, -1), 0.8, colors.HexColor('#999999')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 2.5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ]
        for i, r in enumerate(t.rows, start=1):
            if i - 1 in t.groups:
                rows.append([Paragraph(f'<b>{escape(r[0])}</b>', cell)] + [''] * (len(t.columns) - 1))
                style += [('SPAN', (0, i), (-1, i)), ('BACKGROUND', (0, i), (-1, i), colors.HexColor('#FAF8F7'))]
                continue
            rows.append([Paragraph(escape(c), num if j and NUMERIC.match(c) else cell) for j, c in enumerate(r)])
        first = 0.3 if len(t.columns) > 3 else 0.4
        widths = [doc.width * first] + [doc.width * (1 - first) / (len(t.columns) - 1)] * (len(t.columns) - 1)
        grid = Table(rows, colWidths=widths, repeatRows=1, hAlign='LEFT')
        grid.setStyle(TableStyle(style))
        label = f'{t.label}：' if numbered and t.label else ''
        return [Paragraph(escape(label + t.title), cap), grid, Paragraph('数据来源：' + escape(t.source), small)]

    def figure(c, width):
        return [Paragraph(escape(f'{c.label}：{c.title}'), cap), to_drawing(c, width), Paragraph('数据来源：' + escape(c.source), small)]

    def figure_row(items, story):
        for start in range(0, len(items), 2):
            pair = items[start : start + 2]
            if len(pair) == 1:
                story.append(KeepTogether(figure(pair[0], doc.width * 0.72)))
                continue
            half = doc.width / 2 - 6
            grid = Table([[figure(c, half) for c in pair]], colWidths=[doc.width / 2] * 2, hAlign='LEFT')
            grid.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0)]))
            story.append(grid)

    def blocks(items, story):
        row = []
        for kind, item in items + [('end', None)]:
            if kind == 'chart':
                row.append(item)
                continue
            if row:
                figure_row(row, story)
                row = []
            if kind == 'p':
                story.append(para(item))
            elif kind == 'table':
                parts = data_table(item)
                story.extend([KeepTogether(parts)] if len(item.rows) < 25 else parts)

    story = [Paragraph(escape(view.subtitle), small), Paragraph(escape(view.title), title), Paragraph('核心观点：', h2)]
    for h, b in view.points:
        story.append(Paragraph((f'<b>{escape(h)}</b>' if h else '') + escape(b), body))
    if view.forecast_table:
        story += data_table(view.forecast_table, numbered=False)
    story.append(PageBreak())

    contents = TableOfContents()
    contents.levelStyles = [
        ParagraphStyle('toc1', parent=body, fontName=bold, leftIndent=0, spaceAfter=2),
        ParagraphStyle('toc2', parent=body, fontSize=9.5, leftIndent=14, spaceAfter=1),
        ParagraphStyle('toc3', parent=body, fontSize=9, leftIndent=28, spaceAfter=1),
    ]
    story += [Paragraph('目录索引', h1), contents]
    figures = view.figures()
    if figures:
        story.append(Paragraph('图表索引', h1))
        story += [Paragraph(escape(f'{f.label}：{f.title}'), small) for f in figures]
    story.append(PageBreak())

    def section(s):
        heading = Paragraph(escape(s.title), {1: h1, 2: h2}.get(s.level, h3))
        heading.toc_entry = (min(s.level - 1, 2), s.title, s.section_id)
        story.append(heading)
        blocks(s.blocks, story)
        for child in s.children:
            section(child)

    for s in view.sections:
        if s.blocks or s.children:
            section(s)
    if view.appendix:
        story.append(PageBreak())
        heading = Paragraph('附录：财务报表', h1)
        heading.toc_entry = (0, '附录：财务报表', 'appendix')
        story.append(heading)
        for t in view.appendix:
            story += data_table(t, numbered=False)
            story.append(Spacer(1, 6))
    story += [Spacer(1, 12), Paragraph('免责声明：' + escape(view.disclaimer), small)]
    doc.multiBuild(story, maxPasses=8)
