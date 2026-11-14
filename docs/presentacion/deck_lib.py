from pathlib import Path

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.dml import MSO_LINE_DASH_STYLE

ROOT = Path(r"C:\Users\lodo1\Desktop\PROYECTOS\PROYECTOS\Personal\TuPedidoJR")
OUT = ROOT / "docs" / "presentacion"
LOGO = ROOT / "backend" / "static" / "logo.png"

NAVY = RGBColor(0x1B, 0x2F, 0x6B)
NAVY_DARK = RGBColor(0x12, 0x22, 0x4F)
ORANGE = RGBColor(0xF5, 0x82, 0x20)
ORANGE_DARK = RGBColor(0xC9, 0x62, 0x0E)
LIGHT = RGBColor(0xF4, 0xF6, 0xFA)
LIGHT2 = RGBColor(0xEB, 0xEF, 0xF7)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GRAY = RGBColor(0x5B, 0x65, 0x75)
GRAY_LIGHT = RGBColor(0x9A, 0xA4, 0xB2)
GREEN = RGBColor(0x2E, 0x7D, 0x32)
RED = RGBColor(0xC6, 0x28, 0x28)
FONT = "Segoe UI"


def new_deck():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    return prs


def blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def add_text(slide, x, y, w, h, text, size=14, color=NAVY, bold=False,
             align=PP_ALIGN.LEFT, italic=False, spacing=1.0,
             anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    p = tf.paragraphs[0]
    p.alignment = align
    p.line_spacing = spacing
    r = p.add_run()
    r.text = text
    r.font.name = FONT
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.italic = italic
    r.font.color.rgb = color
    return box


def add_rect(slide, x, y, w, h, fill, line=None, rounded=False, radius=0.06):
    shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE
    shape = slide.shapes.add_shape(shape_type, Inches(x), Inches(y), Inches(w), Inches(h))
    if rounded:
        try:
            shape.adjustments[0] = radius
        except Exception:
            pass
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line
        shape.line.width = Pt(1)
    try:
        shape.shadow.inherit = False
    except Exception:
        pass
    return shape


def add_circle(slide, x, y, d, fill, line=None):
    shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(d), Inches(d))
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line
        shape.line.width = Pt(1.5)
    try:
        shape.shadow.inherit = False
    except Exception:
        pass
    return shape


def add_line(slide, x1, y1, x2, y2, color=LIGHT2, width=1.0, dash=None):
    line = slide.shapes.add_connector(1, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    line.line.color.rgb = color
    line.line.width = Pt(width)
    if dash:
        line.line.dash_style = dash
    return line


def add_logo(slide, x, y, w, on_dark=False):
    if on_dark:
        add_rect(slide, x - 0.18, y - 0.12, w + 0.36, 0.85, WHITE, rounded=True, radius=0.12)
    slide.shapes.add_picture(str(LOGO), Inches(x), Inches(y), width=Inches(w))


def add_footer(slide, number, dark=False):
    color = RGBColor(0xB8, 0xC2, 0xD6) if dark else GRAY_LIGHT
    line_color = RGBColor(0x2B, 0x40, 0x80) if dark else LIGHT2
    add_line(slide, 0.62, 7.08, 12.72, 7.08, color=line_color, width=0.75)
    add_text(slide, 0.62, 7.15, 9.0, 0.25, "TuPedidoJR · Juventino Rosas, Gto. · 2026",
             size=8.5, color=color)
    add_text(slide, 11.9, 7.15, 0.82, 0.25, f"{number:02d}", size=8.5,
             color=color, align=PP_ALIGN.RIGHT)


def add_slide_base(prs, title, kicker=None, subtitle=None, number=1, dark=False):
    slide = blank(prs)
    bg = NAVY_DARK if dark else WHITE
    add_rect(slide, 0, 0, 13.333, 7.5, bg)
    if not dark:
        add_rect(slide, 0, 0, 13.333, 0.07, ORANGE)
    if kicker:
        add_text(slide, 0.62, 0.33, 11.8, 0.28, kicker.upper(),
                 size=10.5, color=ORANGE, bold=True)
    add_text(slide, 0.62, 0.62, 12.1, 0.6, title,
             size=28, color=WHITE if dark else NAVY, bold=True)
    y = 1.24
    if subtitle:
        add_text(slide, 0.62, y, 11.8, 0.55, subtitle,
                 size=13.5, color=RGBColor(0xC9, 0xD2, 0xE3) if dark else GRAY,
                 spacing=1.05)
        y += 0.55
    add_line(slide, 0.62, y + 0.12, 12.72, y + 0.12,
             color=RGBColor(0x2B, 0x40, 0x80) if dark else LIGHT2, width=0.8)
    add_footer(slide, number, dark=dark)
    return slide


def add_card(slide, x, y, w, h, fill=LIGHT, line=None, radius=0.08):
    return add_rect(slide, x, y, w, h, fill, line=line, rounded=True, radius=radius)


def add_kpi(slide, x, y, w, h, value, label, note="", accent=ORANGE,
            value_size=31, fill=LIGHT):
    add_card(slide, x, y, w, h, fill=fill)
    add_rect(slide, x + 0.18, y, 0.06, h, accent)
    add_text(slide, x + 0.36, y + 0.18, w - 0.5, 0.55, value,
             size=value_size, color=NAVY, bold=True)
    add_text(slide, x + 0.36, y + 0.78, w - 0.5, 0.32, label,
             size=11, color=NAVY, bold=True)
    if note:
        add_text(slide, x + 0.36, y + 1.12, w - 0.5, 0.5, note,
                 size=9, color=GRAY, spacing=1.0)


def add_bullets(slide, x, y, w, h, items, size=14, color=NAVY,
                bullet_color=ORANGE, spacing=8, line_spacing=1.05):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(spacing)
        p.line_spacing = line_spacing
        r = p.add_run()
        r.text = "✓  "
        r.font.name = FONT
        r.font.size = Pt(size)
        r.font.bold = True
        r.font.color.rgb = bullet_color
        r2 = p.add_run()
        r2.text = item
        r2.font.name = FONT
        r2.font.size = Pt(size)
        r2.font.color.rgb = color
    return box


def add_table(slide, x, y, w, h, headers, rows, col_widths,
              header_fill=NAVY, header_color=WHITE, font_size=10,
              row_height=0.52, center_columns=True):
    shape = slide.shapes.add_table(len(rows) + 1, len(headers), Inches(x), Inches(y),
                                   Inches(w), Inches(h))
    table = shape.table
    for i, width in enumerate(col_widths):
        table.columns[i].width = Inches(width)
    table.rows[0].height = Inches(0.48)
    for i in range(1, len(rows) + 1):
        table.rows[i].height = Inches(row_height)
    for c, header in enumerate(headers):
        cell = table.cell(0, c)
        cell.fill.solid()
        cell.fill.fore_color.rgb = header_fill
        cell.margin_left = Inches(0.08)
        cell.margin_right = Inches(0.08)
        cell.margin_top = Inches(0.04)
        cell.margin_bottom = Inches(0.04)
        tf = cell.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.LEFT if (c == 0 or not center_columns) else PP_ALIGN.CENTER
        r = p.add_run()
        r.text = header
        r.font.name = FONT
        r.font.size = Pt(font_size)
        r.font.bold = True
        r.font.color.rgb = header_color
    for r_idx, row in enumerate(rows, start=1):
        for c_idx, value in enumerate(row):
            cell = table.cell(r_idx, c_idx)
            cell.fill.solid()
            cell.fill.fore_color.rgb = WHITE if r_idx % 2 else LIGHT
            cell.margin_left = Inches(0.08)
            cell.margin_right = Inches(0.08)
            cell.margin_top = Inches(0.04)
            cell.margin_bottom = Inches(0.04)
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.LEFT if (c_idx == 0 or not center_columns) else PP_ALIGN.CENTER
            r = p.add_run()
            r.text = str(value)
            r.font.name = FONT
            r.font.size = Pt(font_size)
            r.font.bold = c_idx == 0
            r.font.color.rgb = NAVY if c_idx == 0 else GRAY
    return table
