from html import escape
from pathlib import Path
from .schemas import ReportDocument
from .reports import sections_flat,toc,paper_table


def render_chart(chart: dict,path: Path):
    from PIL import Image,ImageDraw,ImageFont
    width,height=1200,520;image=Image.new('RGB',(width,height),'white');draw=ImageDraw.Draw(image)
    fonts=[Path('C:/Windows/Fonts/msyh.ttc'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
    font_path=next((p for p in fonts if p.is_file()),None)
    font=ImageFont.truetype(str(font_path),22) if font_path else ImageFont.load_default()
    draw.text((40,25),chart['title']+' / '+chart['unit'],fill='#19303d',font=font)
    values=[float(v) for v in chart['values']];maximum=max(values+[1]);step=1080/max(len(values),1)
    for i,(label,value) in enumerate(zip(chart['labels'],values)):
        x=60+i*step;y=430-max(value,0)/maximum*300
        draw.rectangle((x,y,x+step*.6,430),fill='#166e70')
        draw.text((x,450),label,fill='#19303d',font=font)
        draw.text((x,y-30),f'{value:.0f}',fill='#19303d',font=font)
    path.parent.mkdir(parents=True,exist_ok=True);image.save(path)


def export_pdf(report: ReportDocument,path: Path):
    """ReportLab multi-pass TOC records final page positions; no guessed pages."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import BaseDocTemplate,PageTemplate,Frame,Paragraph,Spacer,Table,TableStyle,PageBreak,Image
    from reportlab.platypus.tableofcontents import TableOfContents
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    body=ParagraphStyle('body',fontName='STSong-Light',fontSize=10,leading=17,spaceAfter=9,wordWrap='CJK')
    small=ParagraphStyle('small',parent=body,fontSize=7.5,leading=11,spaceAfter=4)
    h1=ParagraphStyle('h1',parent=body,fontSize=17,leading=25,spaceBefore=20,spaceAfter=12,keepWithNext=True)
    h2=ParagraphStyle('h2',parent=h1,fontSize=13,leading=20)
    class ReportDoc(BaseDocTemplate):
        def afterFlowable(self,flowable):
            if hasattr(flowable,'toc_entry'):
                level,title,anchor=flowable.toc_entry
                self.canv.bookmarkPage(anchor)
                self.notify('TOCEntry',(level,title,self.page,anchor))
    path.parent.mkdir(parents=True,exist_ok=True)
    doc=ReportDoc(str(path),pagesize=A4,leftMargin=48,rightMargin=48,topMargin=48,bottomMargin=48,title=report.title,author='Company Deep Research Agent')
    frame=Frame(doc.leftMargin,doc.bottomMargin,doc.width,doc.height,id='normal')
    def footer(canvas,document):
        canvas.setFont('STSong-Light',8);canvas.setFillColor(colors.HexColor('#64748b'))
        canvas.drawString(48,25,'Company Deep Research · '+('模拟报告' if report.mode=='mock' else '公司研究'))
        canvas.drawRightString(A4[0]-48,25,str(document.page))
    doc.addPageTemplates(PageTemplate(id='pages',frames=[frame],onPage=footer))
    story=[Paragraph(escape(report.title),h1),Paragraph('模拟运行 合成数据' if report.mode=='mock' else '上市公司深度研究',body)]
    for limitation in report.limitations:story.append(Paragraph(escape(limitation),body))
    table_of_contents=TableOfContents();table_of_contents.levelStyles=[ParagraphStyle('toc1',parent=body,leftIndent=0),ParagraphStyle('toc2',parent=body,leftIndent=14,fontSize=9)]
    def section(s,level=0):
        heading=Paragraph(escape(s.title),h1 if level==0 else h2)
        if s.section_id not in {'core','toc'}:heading.toc_entry=(min(level,1),s.title,s.section_id)
        story.append(heading)
        if s.section_id=='toc':story.extend([table_of_contents,Spacer(1,12)])
        for p in s.paragraphs:
            if p:story.append(Paragraph(escape(p),body))
        for table in s.tables:
            table,reference_notes=paper_table(table)
            story.append(Paragraph(escape(table.title),h2))
            data=[[Paragraph(escape(str(c)),small) for c in row] for row in [table.columns]+table.rows]
            weights=[2 if i==0 else .7 if any(w in c for w in ['来源','引用']) else 1.2 if '状态' in c else 1 for i,c in enumerate(table.columns)]
            widths=[doc.width*w/sum(weights) for w in weights]
            if table.title=='预测假设与依据':widths=[145,55,70,65,doc.width-335]
            t=Table(data,colWidths=widths,repeatRows=1,hAlign='LEFT')
            t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#edf3f5')),('GRID',(0,0),(-1,-1),.3,colors.HexColor('#ccd5dc')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
            story.extend([t,Spacer(1,12)])
            story.extend(Paragraph(escape(note),small) for note in reference_notes)
        if s.evidence_ids:story.append(Paragraph(escape('证据：'+', '.join(s.evidence_ids)),small))
        if s.section_id=='forecast':
            for i,chart in enumerate(report.charts):
                chart_path=path.parent/f'chart-{i}.png';render_chart(chart,chart_path)
                story.extend([Paragraph(escape(chart['title']),h2),Image(str(chart_path),width=doc.width,height=doc.width*520/1200)])
        for child in s.children:section(child,level+1)
    for s in report.sections:section(s)
    story.append(Paragraph('来源及证据',h1))
    for source in report.sources:
        story.append(Paragraph(escape(f'{source.source_id} · {source.title} · {source.locator} · {source.publication_date or "日期未知"} · {source.source_url or source.local_path or "合成材料"}'),small))
    for evidence in report.evidence:
        claim=evidence.claim if len(evidence.claim)<=300 else evidence.claim[:300]+'（完整原文在随附 JSON 中保留）'
        story.append(Paragraph(escape(f'{evidence.evidence_id} · {claim} · [{evidence.source_id}/{evidence.locator}]'),small))
    doc.multiBuild(story,maxPasses=8)
