"""Safe structured rendering; document numbers always originate in Python."""

from html import escape
from pathlib import Path
from .schemas import ReportDocument, ReportSection, Table, SourceRecord

TITLES = [
    "核心观点",
    "目录",
    "一、公司简介",
    "二、财务情况分析",
    "三、公司业务",
    "四、盈利预测与估值",
    "五、风险提示",
    "六、财务三表",
    "七、免责声明",
]


def sections_flat(sections: list[ReportSection]):
    for section in sections:
        yield section
        yield from sections_flat(section.children)


def toc(sections: list[ReportSection]) -> list[tuple[str, str]]:
    return [(s.section_id, s.title) for s in sections_flat(sections) if s.section_id not in {"core", "toc"}]


def paper_table(data):
    """Keep wide references readable: compact markers in cells, complete references immediately below."""
    import hashlib

    reference_columns = [i for i, c in enumerate(data.columns) if any(w in c for w in ['来源', '事实引用', '计算引用'])]
    if len(data.columns) < 8 or not reference_columns:
        return data, []
    prefix = hashlib.sha256(data.title.encode()).hexdigest()[:4]
    rows = []
    notes = []
    for index, row in enumerate(data.rows):
        new = list(row)
        label = f'{prefix}-{index + 1}'
        for i in reference_columns:
            new[i] = '[' + label + ']'
        notes.append('[' + label + '] ' + '；'.join(data.columns[i] + '：' + row[i] for i in reference_columns))
        rows.append(new)
    return data.model_copy(update={'rows': rows}), notes


def mock_report(company: str) -> ReportDocument:
    source = SourceRecord(
        source_id="mock-fixture",
        kind="mock",
        title="模拟财务与经营材料",
        content="所有数据均为程序测试合成，非真实公司资料。",
    )
    sections = [
        ReportSection(section_id=sid, title=title, paragraphs=[text])
        for sid, title, text in [
            (
                "core",
                TITLES[0],
                "本报告为模拟示例，仅验证研究、计算、审核和导出流程。演示公司收入增长与现金创造能力的关系，所有数字均为合成数据，不可用于投资判断。",
            ),
            ("toc", TITLES[1], ""),
            (
                "company",
                TITLES[2],
                f"输入对象为{company}。模拟模式使用虚构的示例制造企业，包含设备和服务两个业务。输入名称不会使模拟材料成为真实资料。",
            ),
            (
                "financial",
                TITLES[3],
                "模拟企业收入增加时，应同时关注应收与库存增长。利润和现金流可能不同步；营运资本占用影响经营现金流，扩产支出影响自由现金流。",
            ),
            ("business", TITLES[4], "从设备与服务两个业务分别分析需求、竞争和经营质量。"),
            (
                "forecast",
                TITLES[5],
                "预测采用公开的示例假设。情景变化由 Python 确定性计算，真实研究需要验证需求、价格、成本和资本开支的来源。",
            ),
            (
                "risk",
                TITLES[6],
                "主要风险为需求波动、客户回款延迟、成本上涨和资本开支超支。模拟数据不反映输入公司的真实风险。",
            ),
            ("statements", TITLES[7], "此阶段仅提供测试报表；完整财务模型由后续计算底座接入。"),
            (
                "disclaimer",
                TITLES[8],
                "本系统生成研究辅助材料，不构成投资建议。模拟报告全部使用虚构资料。预测属于条件推演，不能视为实际业绩或收益保证。",
            ),
        ]
    ]
    for index, name in enumerate(["设备", "服务"]):
        sections[4].children.append(
            ReportSection(
                section_id=f"segment-{index}",
                title=name,
                children=[
                    ReportSection(
                        section_id=f"industry-{index}",
                        title="（一）行业情况",
                        paragraphs=["演示行业分析应识别需求周期、技术替代与竞争结构。真实判断必须依赖可核查证据。"],
                    ),
                    ReportSection(
                        section_id=f"position-{index}",
                        title="（二）公司情况",
                        paragraphs=[
                            "演示经营分析应将客户结构、产能约束和盈利质量联系起来，不将缺少证据的优势写成确定事实。"
                        ],
                    ),
                ],
            )
        )
    sections[7].tables.append(
        Table(
            title="模拟利润表 单位 百万元",
            columns=["项目", "2024A", "2025A"],
            rows=[["营业收入", "1000", "1100"], ["营业成本", "600", "660"]],
        )
    )
    return ReportDocument(
        title=f"{company} 公司深度研究报告",
        company_id="MOCK",
        mode="mock",
        sections=sections,
        sources=[source],
        limitations=["模拟运行：全部材料为合成 Fixture，未调用真实模型或搜索。"],
    )


def html_report(report: ReportDocument) -> str:
    def render(section: ReportSection, level: int = 2) -> str:
        out = f'<section id="{escape(section.section_id, quote=True)}"><h{level}>{escape(section.title)}</h{level}>'
        if section.section_id == "toc":
            out += (
                '<nav aria-label="目录">'
                + ''.join(f'<a href="#{escape(i, quote=True)}">{escape(t)}</a><br>' for i, t in toc(report.sections))
                + '</nav>'
            )
        out += ''.join(f'<p>{escape(p)}</p>' for p in section.paragraphs if p)
        for table in section.tables:
            out += (
                '<table><caption>'
                + escape(table.title)
                + '</caption><thead><tr>'
                + ''.join('<th>' + escape(c) + '</th>' for c in table.columns)
                + '</tr></thead><tbody>'
            )
            out += (
                ''.join('<tr>' + ''.join('<td>' + escape(c) + '</td>' for c in row) + '</tr>' for row in table.rows)
                + '</tbody></table>'
            )
        out += ''.join(render(c, min(level + 1, 6)) for c in section.children)
        if section.evidence_ids:
            out += '<small>证据：' + escape(', '.join(section.evidence_ids)) + '</small>'
        return out + '</section>'

    body = f'<h1>{escape(report.title)}</h1><p>{"模拟运行" if report.mode == "mock" else "真实研究"}</p>'
    body += ''.join(f'<p class="notice">{escape(x)}</p>' for x in report.limitations)
    chart_html = ''
    for chart in report.charts:
        values = [float(v) for v in chart['values']]
        maximum = max(values + [1])
        step = 700 / max(len(values), 1)
        svg = '<svg viewBox="0 0 800 360" role="img" aria-label="' + escape(chart['title'], quote=True) + '">'
        for i, (label, value) in enumerate(zip(chart['labels'], values)):
            x = 50 + i * step
            height = max(value, 0) / maximum * 240
            svg += f'<rect x="{x:.2f}" y="{280 - height:.2f}" width="{step * 0.6:.2f}" height="{height:.2f}" fill="#166e70"/><text x="{x:.2f}" y="310" font-size="14">{escape(label)}</text><text x="{x:.2f}" y="{265 - height:.2f}" font-size="14">{value:.0f}</text>'
        chart_html += (
            '<figure><figcaption>'
            + escape(chart['title'] + ' · ' + chart['unit'])
            + '</figcaption>'
            + svg
            + '</svg></figure>'
        )
    body += ''.join(render(s) + (chart_html if s.section_id == 'forecast' else '') for s in report.sections)
    body += '<h2>来源及证据</h2>'
    for s in report.sources:
        url = s.source_url or ''
        label = escape(s.title)
        if url.startswith(('https://', 'http://')):
            label = f'<a href="{escape(url, quote=True)}" rel="noopener noreferrer">{label}</a>'
        body += f'<p>{escape(s.source_id)} · {label} · {escape(s.locator)} · {escape(s.publication_date or "日期未披露")}</p>'
    body += ''.join(
        f'<p>{escape(e.evidence_id)} · {escape(e.claim)} · {escape(e.source_id)} · {escape(e.locator)}</p>'
        for e in report.evidence
    )
    return (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>'
        + escape(report.title)
        + '</title><style>body{max-width:900px;margin:60px auto;padding:0 24px;font:16px/1.9 system-ui;color:#172b38}h1,h2,h3{line-height:1.4}section{margin-top:40px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #ccd5dc;padding:8px}th{background:#eef3f5}a{color:#136e74}.notice{background:#fff3d6;padding:12px}small{overflow-wrap:anywhere}</style><body>'
        + body
        + '</body></html>'
    )


def export_docx(report: ReportDocument, path: Path) -> None:
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    document = Document()
    sec = document.sections[0]
    sec.top_margin = sec.bottom_margin = Inches(0.8)
    sec.left_margin = sec.right_margin = Inches(0.85)
    for style in ['Normal', 'Title', 'Heading 1', 'Heading 2', 'Heading 3']:
        st = document.styles[style]
        st.font.name = 'Microsoft YaHei'
        st.font.color.rgb = RGBColor(0, 0, 0)
        st.element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')
        for border in list(st.element.iter(qn('w:pBdr'))):
            border.getparent().remove(border)
    document.styles['Normal'].font.size = Pt(11)
    document.styles['Normal'].paragraph_format.space_after = Pt(7)
    for name in ['Heading 1', 'Heading 2', 'Heading 3']:
        document.styles[name].paragraph_format.keep_with_next = True
    document.styles['Normal'].paragraph_format.widow_control = True
    document.add_heading(report.title, 0)
    document.add_paragraph('模拟运行 合成数据' if report.mode == 'mock' else '上市公司研究')
    for limitation in report.limitations:
        document.add_paragraph(limitation)

    def add(section: ReportSection, depth=1):
        document.add_heading(section.title, min(depth, 3))
        if section.section_id == 'toc':
            document.add_paragraph('目录按最终结构生成。以下不标注未经排版核实的页码。')
            for _, title in toc(report.sections):
                document.add_paragraph(title)
        for paragraph in section.paragraphs:
            if paragraph:
                document.add_paragraph(paragraph)
        for data in section.tables:
            data, reference_notes = paper_table(data)
            document.add_paragraph(data.title)
            document.paragraphs[-1].paragraph_format.keep_with_next = True
            table = document.add_table(rows=1, cols=len(data.columns))
            table.style = 'Light Shading Accent 1'
            table.autofit = False
            weights = [
                2 if i == 0 else 0.7 if any(w in c for w in ['来源', '引用']) else 1.2 if '状态' in c else 1
                for i, c in enumerate(data.columns)
            ]
            widths = (
                [1.8, 0.8, 0.8, 0.8, 1.8]
                if data.title == '预测假设与依据'
                else [6.5 * w / sum(weights) for w in weights]
            )
            for column, width in zip(table.columns, widths):
                column.width = Inches(width)
            for cell, value in zip(table.rows[0].cells, data.columns):
                cell.text = value
                for p in cell.paragraphs:
                    p.paragraph_format.keep_with_next = True
            header = OxmlElement('w:tblHeader')
            table.rows[0]._tr.get_or_add_trPr().append(header)
            for row in data.rows:
                for cell, value in zip(table.add_row().cells, row):
                    cell.text = value
            for row in table.rows:
                cant_split = OxmlElement('w:cantSplit')
                row._tr.get_or_add_trPr().append(cant_split)
                for index, cell in enumerate(row.cells):
                    cell.width = Inches(widths[index])
                    for p in cell.paragraphs:
                        for r in p.runs:
                            r.font.size = Pt(8)
            for note in reference_notes:
                p = document.add_paragraph(note)
                for r in p.runs:
                    r.font.size = Pt(8)
        if section.section_id == 'forecast':
            from .renderers import render_chart

            for i, chart in enumerate(report.charts):
                chart_path = path.parent / f'chart-{i}.png'
                render_chart(chart, chart_path)
                document.add_heading(chart['title'], 2)
                document.add_picture(str(chart_path), width=Inches(6.5))
        if section.evidence_ids:
            document.add_paragraph('证据：' + ', '.join(section.evidence_ids))
        for child in section.children:
            add(child, depth + 1)

    for section in report.sections:
        add(section)
    document.add_heading('来源及证据', 1)
    for source in report.sources:
        p = document.add_paragraph(
            f'{source.source_id} {source.title} {source.source_url or source.local_path or "合成材料"} {source.locator} {source.publication_date or "日期未知"}'
        )
        for r in p.runs:
            r.font.size = Pt(8)
    for ev in report.evidence:
        claim = ev.claim if len(ev.claim) <= 300 else ev.claim[:300] + '（完整原文与证据在随附 JSON 中保留）'
        p = document.add_paragraph(f'{ev.evidence_id} {claim} [{ev.source_id} {ev.locator}]')
        for r in p.runs:
            r.font.size = Pt(8)
    footer = sec.footer.paragraphs[0]
    footer.alignment = 2
    field = OxmlElement('w:fldSimple')
    field.set(qn('w:instr'), 'PAGE')
    footer._p.append(field)
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(path)
