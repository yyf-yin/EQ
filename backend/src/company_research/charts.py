"""Report charts: one primitive scene, three backends (SVG for HTML, PNG for DOCX, vector for PDF).

Charts are drawn from verified facts only; a series with no values is dropped and a
chart without any plotted value is never produced.
"""

import math
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

PALETTE = ['#1F4E79', '#C0392B', '#E3A21A', '#2E8B57', '#7F7F7F', '#5B9BD5']
INK = '#333333'
GRID = '#DDDDDD'
WIDTH, HEIGHT = 560, 340
FONT_FILES = [
    Path('C:/Windows/Fonts/msyh.ttc'),
    Path('C:/Windows/Fonts/simhei.ttf'),
    Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
    Path('/usr/share/fonts/truetype/wqy/wqy-microhei.ttc'),
    Path('/System/Library/Fonts/PingFang.ttc'),
]


@dataclass
class Series:
    name: str
    values: list
    kind: str = 'bar'  # bar | line
    axis: str = 'left'  # left | right


@dataclass
class Chart:
    title: str
    categories: list[str]
    series: list[Series]
    unit: str = ''
    right_unit: str = ''
    kind: str = 'combo'  # combo | stacked | pie
    source: str = '公司公告'
    keywords: tuple = ()
    labels: bool = True
    label: str = ''  # 图N, assigned when the report is laid out

    def usable(self) -> bool:
        self.series = [s for s in self.series if any(v is not None for v in s.values)]
        return bool(self.categories) and bool(self.series)


# ---------------------------------------------------------------- scene


@dataclass
class Prim:
    kind: str  # rect | line | poly | circle | text | wedge
    args: dict = field(default_factory=dict)


def text_width(text: str, size: float) -> float:
    return sum(size * (0.55 if ord(ch) < 128 else 1.0) for ch in text)


def nice_step(raw: float) -> float:
    magnitude = 10 ** math.floor(math.log10(raw))
    return next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)


def nice_ticks(low: float, high: float, count: int = 5, zero: bool = True) -> list[float]:
    if zero:
        low, high = min(low, 0.0), max(high, 0.0)
    else:
        # Keep small moves in proportion: pad by at least 5% of the level.
        pad = max((high - low) * 0.3, max(abs(high), abs(low)) * 0.05) or 1
        low, high = low - pad, high + pad
    if high == low:
        high = low + 1
    step = nice_step((high - low) / count)
    start = math.floor(low / step) * step
    ticks = []
    value = start
    while value < high + step * 0.999:
        ticks.append(round(value, 10))
        value += step
    return ticks


def aligned_ticks(low: float, high: float, intervals: int) -> list[float]:
    """Right-axis ticks on the same gridlines as the left axis."""
    low, high = min(low, 0.0), max(high, 0.0)
    step = nice_step(((high - low) or 1) / intervals)
    start = math.floor(low / step) * step
    while start + step * intervals < high:
        step = nice_step(step * 1.01)
        start = math.floor(low / step) * step
    return [round(start + step * i, 10) for i in range(intervals + 1)]


def fmt(value: float, unit: str = '') -> str:
    if unit == '%':
        return f'{value:.1f}%'
    if abs(value) >= 1000:
        return f'{value:,.0f}'
    if abs(value) >= 100:
        return f'{value:.0f}'
    if abs(value) >= 10:
        return f'{value:.1f}'
    return f'{value:.2f}'.rstrip('0').rstrip('.') if value else '0'


def axis_label(value: float, unit: str, step: float) -> str:
    places = max(0, -math.floor(math.log10(step))) if step < 1 else 0
    text = f'{value:,.{places}f}'
    return text + '%' if unit == '%' else text


def scene(chart: Chart, width: float = WIDTH, height: float = HEIGHT) -> list[Prim]:
    if chart.kind == 'pie':
        return pie_scene(chart, width, height)
    prims: list[Prim] = []
    bars = [s for s in chart.series if s.kind == 'bar']
    lines = [s for s in chart.series if s.kind == 'line']
    right = [s for s in lines if s.axis == 'right']
    left_series = bars + [s for s in lines if s.axis != 'right']
    colors = {id(s): PALETTE[i % len(PALETTE)] for i, s in enumerate(chart.series)}

    # Legend across the top.
    x, y = 16.0, 16.0
    for s in chart.series:
        color = colors[id(s)]
        label = s.name + (f'（右轴，{chart.right_unit}）' if s in right and chart.right_unit else '')
        if x > 16 and x + 18 + text_width(label, 13) > width - 8:
            x, y = 16.0, y + 20
        if s.kind == 'bar':
            prims.append(Prim('rect', dict(x=x, y=y - 5, w=12, h=10, fill=color)))
        else:
            prims.append(Prim('line', dict(x1=x, y1=y, x2=x + 14, y2=y, stroke=color, width=2)))
            prims.append(Prim('circle', dict(cx=x + 7, cy=y, r=2.6, fill=color)))
        prims.append(Prim('text', dict(x=x + 18, y=y, text=label, size=13, anchor='start')))
        x += 30 + text_width(label, 13)

    left, top, bottom = 62.0, y + 28, height - 36
    plot_right = width - (52 if right else 18)

    def extent(series, stacked=False):
        values = []
        if stacked:
            for i in range(len(chart.categories)):
                pos = sum(v for s in series if (v := s.values[i]) is not None and v > 0)
                neg = sum(v for s in series if (v := s.values[i]) is not None and v < 0)
                values += [pos, neg]
        else:
            values = [v for s in series for v in s.values if v is not None]
        return (min(values), max(values)) if values else (0.0, 1.0)

    stacked = chart.kind == 'stacked' and len(bars) > 1
    low, high = extent(left_series, stacked)
    ticks = nice_ticks(low, high, zero=bool(bars) or low <= 0)
    scale_min, scale_max = ticks[0], ticks[-1]

    def ly(v):
        return bottom - (v - scale_min) / (scale_max - scale_min) * (bottom - top)

    for t in ticks:
        yy = ly(t)
        prims.append(Prim('line', dict(x1=left, y1=yy, x2=plot_right, y2=yy, stroke=GRID, width=0.8)))
        prims.append(Prim('text', dict(x=left - 6, y=yy, text=axis_label(t, chart.unit, ticks[1] - ticks[0]), size=12, anchor='end')))
    if chart.unit and chart.unit != '%':
        prims.append(Prim('text', dict(x=left - 6, y=top - 12, text=chart.unit, size=12, anchor='end')))
    if right:
        rlow, rhigh = extent(right)
        rticks = aligned_ticks(rlow, rhigh, len(ticks) - 1)
        rmin, rmax = rticks[0], rticks[-1]

        def ry(v):
            return bottom - (v - rmin) / (rmax - rmin) * (bottom - top)

        for t in rticks:
            prims.append(Prim('text', dict(x=plot_right + 6, y=ry(t), text=axis_label(t, chart.right_unit, rticks[1] - rticks[0]), size=12, anchor='start')))
    zero = ly(0.0) if scale_min <= 0 <= scale_max else bottom
    prims.append(Prim('line', dict(x1=left, y1=zero, x2=plot_right, y2=zero, stroke='#999999', width=1)))

    n = len(chart.categories)
    slot = (plot_right - left) / n
    size = 12 if n <= 6 else 10.5 if n <= 9 else 9
    for i, label in enumerate(chart.categories):
        prims.append(Prim('text', dict(x=left + slot * (i + 0.5), y=bottom + 14, text=label, size=size, anchor='middle')))

    if bars:
        group = slot * 0.62
        each = group if stacked else group / len(bars)
        offsets = [0.0] * n
        negatives = [0.0] * n
        for b, s in enumerate(bars):
            for i, v in enumerate(s.values):
                if v is None:
                    continue
                x0 = left + slot * i + (slot - group) / 2 + (0 if stacked else each * b)
                if stacked:
                    base = offsets[i] if v >= 0 else negatives[i]
                    y1, y2 = ly(base), ly(base + v)
                    if v >= 0:
                        offsets[i] += v
                    else:
                        negatives[i] += v
                else:
                    y1, y2 = zero, ly(v)
                prims.append(Prim('rect', dict(x=x0, y=min(y1, y2), w=each * 0.92, h=abs(y2 - y1), fill=colors[id(s)])))
                if chart.labels and len(bars) == 1 and n <= 10:
                    prims.append(Prim('text', dict(x=x0 + each * 0.46, y=min(y1, y2) - 8, text=fmt(v), size=11, anchor='middle')))
    for s in lines:
        to_y = ry if s in right else ly
        points = [(left + slot * (i + 0.5), to_y(v)) for i, v in enumerate(s.values) if v is not None]
        if len(points) > 1:
            prims.append(Prim('poly', dict(points=points, stroke=colors[id(s)], width=2)))
        for (px, py), v in zip(points, [v for v in s.values if v is not None]):
            prims.append(Prim('circle', dict(cx=px, cy=py, r=2.8, fill=colors[id(s)])))
            if chart.labels and len(lines) == 1 and not bars and n <= 10:
                unit = chart.right_unit if s in right else chart.unit
                prims.append(Prim('text', dict(x=px, y=py - 10, text=fmt(v, unit), size=11, anchor='middle', fill=colors[id(s)])))
    return prims


def pie_scene(chart: Chart, width: float, height: float) -> list[Prim]:
    values = [(c, v) for c, v in zip(chart.categories, chart.series[0].values) if v and v > 0]
    total = sum(v for _, v in values) or 1
    cx, cy, r = width * 0.36, height / 2 + 6, min(width, height) * 0.36
    prims = []
    angle = 90.0
    for i, (label, v) in enumerate(values):
        sweep = v / total * 360
        color = PALETTE[i % len(PALETTE)]
        prims.append(Prim('wedge', dict(cx=cx, cy=cy, r=r, start=angle - sweep, end=angle, fill=color)))
        mid = math.radians(angle - sweep / 2)
        prims.append(
            Prim('text', dict(x=cx + r * 0.62 * math.cos(mid), y=cy - r * 0.62 * math.sin(mid), text=f'{v / total:.0%}', size=12, anchor='middle', fill='#FFFFFF'))
        )
        ly = 60 + i * 22
        prims.append(Prim('rect', dict(x=width * 0.68, y=ly - 6, w=12, h=12, fill=color)))
        prims.append(Prim('text', dict(x=width * 0.68 + 18, y=ly, text=f'{label}  {fmt(v)}{chart.unit}', size=13, anchor='start')))
        angle -= sweep
    return prims


# ---------------------------------------------------------------- backends


def to_svg(chart: Chart, width: float = WIDTH, height: float = HEIGHT) -> str:
    family = "'Microsoft YaHei','PingFang SC','Noto Sans CJK SC',SimHei,sans-serif"
    out = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="{escape(chart.title, quote=True)}" font-family="{family}">'
    ]
    for p in scene(chart, width, height):
        a = p.args
        if p.kind == 'rect':
            out.append(f'<rect x="{a["x"]:.1f}" y="{a["y"]:.1f}" width="{a["w"]:.1f}" height="{a["h"]:.1f}" fill="{a["fill"]}"/>')
        elif p.kind == 'line':
            out.append(f'<line x1="{a["x1"]:.1f}" y1="{a["y1"]:.1f}" x2="{a["x2"]:.1f}" y2="{a["y2"]:.1f}" stroke="{a["stroke"]}" stroke-width="{a["width"]}"/>')
        elif p.kind == 'poly':
            pts = ' '.join(f'{x:.1f},{y:.1f}' for x, y in a['points'])
            out.append(f'<polyline points="{pts}" fill="none" stroke="{a["stroke"]}" stroke-width="{a["width"]}"/>')
        elif p.kind == 'circle':
            out.append(f'<circle cx="{a["cx"]:.1f}" cy="{a["cy"]:.1f}" r="{a["r"]}" fill="{a["fill"]}"/>')
        elif p.kind == 'wedge':
            s, e = math.radians(a['start']), math.radians(a['end'])
            x1, y1 = a['cx'] + a['r'] * math.cos(e), a['cy'] - a['r'] * math.sin(e)
            x2, y2 = a['cx'] + a['r'] * math.cos(s), a['cy'] - a['r'] * math.sin(s)
            large = 1 if a['end'] - a['start'] > 180 else 0
            out.append(
                f'<path d="M{a["cx"]:.1f},{a["cy"]:.1f} L{x1:.1f},{y1:.1f} A{a["r"]:.1f},{a["r"]:.1f} 0 {large} 1 {x2:.1f},{y2:.1f} Z" fill="{a["fill"]}" stroke="#FFFFFF"/>'
            )
        elif p.kind == 'text':
            anchor = a.get('anchor', 'start')
            out.append(
                f'<text x="{a["x"]:.1f}" y="{a["y"]:.1f}" dy="0.35em" font-size="{a["size"]}" text-anchor="{anchor}" fill="{a.get("fill", INK)}">{escape(a["text"])}</text>'
            )
    return ''.join(out) + '</svg>'


def font_path():
    return next((p for p in FONT_FILES if p.is_file()), None)


def to_png(chart: Chart, path, scale: int = 3):
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new('RGB', (int(WIDTH * scale), int(HEIGHT * scale)), 'white')
    draw = ImageDraw.Draw(image)
    source = font_path()
    fonts = {}

    def font(size):
        key = round(size * scale)
        if key not in fonts:
            fonts[key] = ImageFont.truetype(str(source), key) if source else ImageFont.load_default()
        return fonts[key]

    k = scale
    for p in scene(chart):
        a = p.args
        if p.kind == 'rect':
            draw.rectangle([a['x'] * k, a['y'] * k, (a['x'] + a['w']) * k, (a['y'] + a['h']) * k], fill=a['fill'])
        elif p.kind == 'line':
            draw.line([a['x1'] * k, a['y1'] * k, a['x2'] * k, a['y2'] * k], fill=a['stroke'], width=max(1, round(a['width'] * k)))
        elif p.kind == 'poly':
            draw.line([(x * k, y * k) for x, y in a['points']], fill=a['stroke'], width=round(a['width'] * k), joint='curve')
        elif p.kind == 'circle':
            r = a['r'] * k
            draw.ellipse([a['cx'] * k - r, a['cy'] * k - r, a['cx'] * k + r, a['cy'] * k + r], fill=a['fill'])
        elif p.kind == 'wedge':
            r = a['r'] * k
            box = [a['cx'] * k - r, a['cy'] * k - r, a['cx'] * k + r, a['cy'] * k + r]
            draw.pieslice(box, -a['end'], -a['start'], fill=a['fill'], outline='white', width=k)
        elif p.kind == 'text':
            anchor = {'start': 'lm', 'middle': 'mm', 'end': 'rm'}[a.get('anchor', 'start')]
            draw.text((a['x'] * k, a['y'] * k), a['text'], fill=a.get('fill', INK), font=font(a['size']), anchor=anchor)
    if isinstance(path, Path):
        path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format='PNG')
    return path


def pdf_font():
    """A TrueType CJK font for vector PDF charts, or the built-in CID font as fallback."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if 'ChartCJK' in pdfmetrics.getRegisteredFontNames():
        return 'ChartCJK'
    source = font_path()
    if source:
        try:
            options = {'subfontIndex': 0} if source.suffix == '.ttc' else {}
            pdfmetrics.registerFont(TTFont('ChartCJK', str(source), **options))
            return 'ChartCJK'
        except Exception:
            pass
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    return 'STSong-Light'


def to_drawing(chart: Chart, width: float):
    """ReportLab Drawing scaled to the given width (points)."""
    from reportlab.graphics.shapes import Circle, Drawing, Group, Line, PolyLine, Rect, String, Wedge
    from reportlab.lib.colors import HexColor

    font = pdf_font()
    k = width / WIDTH
    drawing = Drawing(width, HEIGHT * k)
    group = Group()
    H = HEIGHT
    for p in scene(chart):
        a = p.args
        if p.kind == 'rect':
            group.add(Rect(a['x'], H - a['y'] - a['h'], a['w'], a['h'], fillColor=HexColor(a['fill']), strokeColor=None))
        elif p.kind == 'line':
            group.add(Line(a['x1'], H - a['y1'], a['x2'], H - a['y2'], strokeColor=HexColor(a['stroke']), strokeWidth=a['width']))
        elif p.kind == 'poly':
            flat = [c for x, y in a['points'] for c in (x, H - y)]
            group.add(PolyLine(flat, strokeColor=HexColor(a['stroke']), strokeWidth=a['width']))
        elif p.kind == 'circle':
            group.add(Circle(a['cx'], H - a['cy'], a['r'], fillColor=HexColor(a['fill']), strokeColor=None))
        elif p.kind == 'wedge':
            group.add(Wedge(a['cx'], H - a['cy'], a['r'], a['start'], a['end'], fillColor=HexColor(a['fill']), strokeColor=HexColor('#FFFFFF')))
        elif p.kind == 'text':
            group.add(
                String(a['x'], H - a['y'] - a['size'] * 0.35, a['text'], fontName=font, fontSize=a['size'],
                       textAnchor=a.get('anchor', 'start'), fillColor=HexColor(a.get('fill', INK)))
            )
    group.scale(k, k)
    drawing.add(group)
    return drawing
