from pathlib import Path

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from PIL import Image

ROOT = Path(r"C:\Users\lodo1\Desktop\PROYECTOS\PROYECTOS\Personal\TuPedidoJR")
OUT = ROOT / "docs" / "presentacion"
OUT.mkdir(parents=True, exist_ok=True)
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

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]


def add_text(slide, x, y, w, h, text, size=14, color=NAVY, bold=False,
             align=PP_ALIGN.LEFT, italic=False, spacing=1.0,
             anchor=MSO_ANCHOR.TOP, font=FONT):
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
    r.font.name = font
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.italic = italic
    r.font.color.rgb = color
    return box


def add_rich_text(slide, x, y, w, h, parts, size=14, spacing=1.0):
    """parts: list of (text, color, bold) for a single paragraph."""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.line_spacing = spacing
    for text, color, bold in parts:
        r = p.add_run()
        r.text = text
        r.font.name = FONT
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = color
    return box


def add_rect(slide, x, y, w, h, fill, line=None, rounded=False, radius=0.06,
             transparency=None):
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
    if transparency is not None:
        try:
            shape.fill.transparency = transparency
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


def add_slide_base(title, kicker=None, subtitle=None, number=1, dark=False):
    slide = prs.slides.add_slide(BLANK)
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
                 size=13.5, color=RGBColor(0xC9,0xD2,0xE3) if dark else GRAY,
                 spacing=1.05)
        y += 0.55
    add_line(slide, 0.62, y + 0.12, 12.72, y + 0.12,
             color=RGBColor(0x2B,0x40,0x80) if dark else LIGHT2, width=0.8)
    add_footer(slide, number, dark=dark)
    return slide, y + 0.35


def add_card(slide, x, y, w, h, fill=LIGHT, line=None, radius=0.08):
    return add_rect(slide, x, y, w, h, fill, line=line, rounded=True, radius=radius)


def add_kpi(slide, x, y, w, h, value, label, note="", accent=ORANGE,
            value_size=31, fill=LIGHT):
    add_card(slide, x, y, w, h, fill=fill)
    add_rect(slide, x + 0.18, y, 0.06, h, accent)
    add_text(slide, x + 0.36, y + 0.22, w - 0.5, 0.55, value,
             size=value_size, color=NAVY, bold=True)
    add_text(slide, x + 0.36, y + 0.86, w - 0.5, 0.32, label,
             size=11, color=NAVY, bold=True)
    if note:
        add_text(slide, x + 0.36, y + 1.2, w - 0.5, 0.55, note,
                 size=9, color=GRAY, spacing=1.0)


def add_bullets(slide, x, y, w, h, items, size=14, color=NAVY,
                bullet_color=ORANGE, spacing=0.8, line_spacing=1.05):
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
              row_height=0.52, first_col_bold=True, center_columns=True):
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
            r.font.bold = bool(first_col_bold and c_idx == 0)
            r.font.color.rgb = NAVY if c_idx == 0 else GRAY
    return table


# ---------------------------------------------------------------- Slide 1
slide = prs.slides.add_slide(BLANK)
add_rect(slide, 0, 0, 13.333, 7.5, NAVY_DARK)
add_rect(slide, 0, 0, 0.16, 7.5, ORANGE)
add_circle(slide, 10.9, -1.1, 3.4, RGBColor(0x24, 0x3B, 0x7A))
add_circle(slide, 11.6, 5.7, 2.2, RGBColor(0x22, 0x35, 0x6E))
add_text(slide, 0.85, 0.75, 4.0, 0.35, "PROPUESTA 2026", size=11,
         color=ORANGE, bold=True)
add_logo(slide, 0.85, 1.3, 5.25, on_dark=True)
add_text(slide, 0.85, 3.05, 10.6, 0.85,
         "La plataforma local que sí deja crecer\na los restaurantes.",
         size=36, color=WHITE, bold=True, spacing=0.95)
add_text(slide, 0.85, 4.25, 9.8, 0.72,
         "Menú digital, pedidos y reparto con costo fijo, sin comisiones\nporcentuales sobre los alimentos.",
         size=16, color=RGBColor(0xC9,0xD2,0xE3), spacing=1.1)
chips = [("$500/año", "afiliación"), ("0%", "comisión por platillo"), ("100%", "del envío al repartidor")]
x = 0.85
for value, label in chips:
    add_card(slide, x, 5.45, 3.5, 0.78, fill=RGBColor(0x22,0x35,0x6E), radius=0.1)
    add_text(slide, x + 0.2, 5.53, 1.15, 0.35, value, size=16, color=ORANGE, bold=True)
    add_text(slide, x + 0.2, 5.88, 3.0, 0.25, label, size=9, color=RGBColor(0xC9,0xD2,0xE3))
    x += 3.75
add_text(slide, 0.85, 6.85, 9.5, 0.28,
         "Juventino Rosas, Guanajuato  ·  Documento para restaurantes e inversionistas",
         size=9, color=RGBColor(0x9F,0xAD,0xC8))

# ---------------------------------------------------------------- Slide 2
slide, y = add_slide_base(
    "Un modelo simple, transparente y ya operativo",
    kicker="Resumen ejecutivo", number=2,
    subtitle="TuPedidoJR digitaliza restaurantes locales con menú propio, QR, pedidos y reparto respaldado por la plataforma. El restaurante conserva su margen; el cliente sabe exactamente qué paga."
)
kpis = [
    ("$500 / año", "Afiliación por restaurante", "Incluye menú, materiales y soporte."),
    ("$5 / pedido", "Cuota fija al restaurante", "Sin porcentaje sobre alimentos."),
    ("0%", "Comisión sobre platillos", "El precio del menú es del restaurante."),
    ("100%", "Del envío + propina", "Para el repartidor."),
]
x = 0.62
for value, label, note in kpis:
    add_kpi(slide, x, 2.0, 2.93, 1.95, value, label, note, value_size=28)
    x += 3.06
add_card(slide, 0.62, 4.35, 12.1, 1.55, fill=LIGHT2)
add_text(slide, 0.9, 4.55, 11.6, 0.34,
         "Plataforma en producción, no un prototipo", size=15, color=NAVY, bold=True)
add_text(slide, 0.9, 4.95, 11.6, 0.75,
         "App Android, panel web para restaurantes, pagos en efectivo y transferencia, notificaciones push, seguimiento GPS, ETA, liquidaciones y auditoría. Piloto operativo en Juventino Rosas.",
         size=11.5, color=GRAY, spacing=1.1)

# ---------------------------------------------------------------- Slide 3
slide, y = add_slide_base(
    "El modelo de los marketplaces castiga el margen del restaurante",
    kicker="El problema", number=3,
    subtitle="Los restaurantes ganan visibilidad, pero pagan un precio alto: comisiones, pérdida de control y poca claridad en la operación."
)
problems = [
    ("20–30%", "Comisión típica por pedido", "Se descuenta del valor de los alimentos, no de la ganancia."),
    ("$0", "Control del canal digital", "El cliente, los datos y la relación viven en el marketplace."),
    ("?", "Claridad en cargos y reparto", "Tarifas dinámicas, reglas cambiantes y soporte lejano."),
]
x = 0.62
for value, label, note in problems:
    add_card(slide, x, 2.05, 3.92, 1.9)
    add_text(slide, x + 0.28, 2.15, 3.35, 0.6, value, size=30, color=ORANGE, bold=True)
    add_text(slide, x + 0.28, 2.8, 3.35, 0.35, label, size=12, color=NAVY, bold=True)
    add_text(slide, x + 0.28, 3.2, 3.35, 0.55, note, size=9.5, color=GRAY, spacing=1.05)
    x += 4.08
add_card(slide, 0.62, 4.35, 12.1, 1.15, fill=RGBColor(0xFF,0xF2,0xE8), line=RGBColor(0xF7,0xD3,0xB5))
add_text(slide, 0.92, 4.55, 11.5, 0.34,
         "En un pedido de $200, una comisión de 25% se lleva $50.", size=18, color=NAVY, bold=True)
add_text(slide, 0.92, 4.95, 11.5, 0.34,
         "El restaurante termina con $150. Con TuPedidoJR recibe $195 por el mismo pedido.", size=13, color=GRAY)
add_text(slide, 0.62, 6.6, 12.0, 0.3,
         "Rango referencial de comisiones de marketplaces en México. Puede variar por ciudad, categoría y convenio.",
         size=8, color=GRAY_LIGHT, italic=True)

# ---------------------------------------------------------------- Slide 4
slide, y = add_slide_base(
    "Tecnología local con costo fijo y marca propia",
    kicker="La solución", number=4,
    subtitle="TuPedidoJR pone la infraestructura; el restaurante conserva su marca, su cliente y su margen."
)
solutions = [
    ("Menú propio + QR", "Página personalizada con fotos, categorías, precios, opciones y horarios."),
    ("Pedidos y pagos", "Efectivo y transferencia disponibles. Desglose claro antes de pagar."),
    ("Reparto respaldado", "La plataforma coordina, monitorea y responde por la entrega."),
    ("Costo predecible", "$500 al año + $5 por pedido. Sin comisión porcentual sobre alimentos."),
]
x = 0.62
for i, (title, desc) in enumerate(solutions):
    col = i % 2
    row = i // 2
    cx = 0.62 + col * 6.15
    cy = 1.95 + row * 2.0
    add_card(slide, cx, cy, 5.95, 1.72)
    add_circle(slide, cx + 0.25, cy + 0.26, 0.42, ORANGE)
    add_text(slide, cx + 0.25, cy + 0.34, 0.42, 0.2, str(i + 1), size=12,
             color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, cx + 0.85, cy + 0.22, 4.8, 0.34, title, size=14.5, color=NAVY, bold=True)
    add_text(slide, cx + 0.85, cy + 0.65, 4.75, 0.8, desc, size=10.5, color=GRAY, spacing=1.08)
add_text(slide, 0.62, 6.2, 12.0, 0.4,
         "Un solo proveedor para menú, pedidos, reparto, notificaciones y liquidaciones.",
         size=13, color=ORANGE_DARK, bold=True)

# ---------------------------------------------------------------- Slide 5 product
slide, y = add_slide_base(
    "Una plataforma completa, ya en operación",
    kicker="Producto", number=5,
    subtitle="Las piezas necesarias para operar un restaurante local ya están construidas y funcionando."
)
features = [
    ("APP", "App Android + web", "La misma experiencia para cliente, restaurante y repartidor."),
    ("QR", "Menú digital", "URL propia, fotos, categorías, opciones y horarios."),
    ("$", "Pagos y cobros", "Efectivo, transferencia y conciliación de pedidos."),
    ("GPS", "Reparto y seguimiento", "Asignación, ubicación en vivo y ETA por ruta."),
    ("PUSH", "Notificaciones", "Avisos de pedido, estado y recordatorios con sonido."),
    ("ML", "Ganancias y liquidaciones", "Cuentas claras para restaurante, repartidor y admin."),
]
for i, (icon, title, desc) in enumerate(features):
    col = i % 3
    row = i // 3
    cx = 0.62 + col * 4.08
    cy = 1.95 + row * 2.05
    add_card(slide, cx, cy, 3.88, 1.78)
    add_circle(slide, cx + 0.24, cy + 0.24, 0.5, LIGHT2)
    add_text(slide, cx + 0.24, cy + 0.38, 0.5, 0.2, icon, size=7.5, color=NAVY,
             bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, cx + 0.88, cy + 0.22, 2.8, 0.3, title, size=12.5, color=NAVY, bold=True)
    add_text(slide, cx + 0.88, cy + 0.62, 2.75, 0.95, desc, size=9.5, color=GRAY, spacing=1.05)
add_card(slide, 0.62, 6.2, 12.1, 0.55, fill=RGBColor(0xE8,0xF5,0xE9))
add_text(slide, 0.9, 6.32, 11.5, 0.3,
         "Ventaja: una sola plataforma reemplaza web, menú, comandas, avisos y control de reparto.",
         size=11, color=GREEN, bold=True)

# ---------------------------------------------------------------- Slide 6 comparison
slide, y = add_slide_base(
    "TuPedidoJR vs. marketplaces tradicionales",
    kicker="Comparativo", number=6,
    subtitle="La diferencia no es solo el precio: es quién controla la relación, el menú y la operación."
)
headers = ["", "TuPedidoJR", "Uber Eats / DiDi Food*"]
rows = [
    ["Costo del restaurante", "$500/año + $5 por pedido", "Comisión de 20–30% por pedido"],
    ["Comisión sobre alimentos", "0%", "20–30% del valor del platillo"],
    ["Menú y marca", "Página propia con URL y QR", "Perfil dentro del marketplace"],
    ["Material físico", "Volantes, acrílico y fotografía incluidos", "No incluido o con costo adicional"],
    ["Costo del cliente", "Envío $25 base + $5/km extra + $5 servicio", "Envío y cargos dinámicos"],
    ["Pago al repartidor", "100% envío + 100% propina", "Modelo variable según plataforma"],
    ["Respaldo de entrega", "Plataforma; pedidos lejanos se retienen", "Asignación del marketplace"],
    ["Relación con el cliente", "Canal directo del restaurante", "Cliente del marketplace"],
]
add_table(slide, 0.62, 1.9, 12.1, 4.8, headers, rows,
          col_widths=[2.55, 4.65, 4.9], font_size=9.3, row_height=0.5)
add_text(slide, 0.62, 6.75, 12.0, 0.25,
         "*Referencia de mercado. No representa una tarifa oficial; verificar términos vigentes de cada plataforma.",
         size=8, color=GRAY_LIGHT, italic=True)

# ---------------------------------------------------------------- Slide 7 unit economics
slide, y = add_slide_base(
    "El restaurante conserva el 97.5% de su venta",
    kicker="Economía por pedido", number=7,
    subtitle="Ejemplo con un pedido de $200, reparto de la plataforma y envío base de 1 km."
)
add_card(slide, 0.62, 1.95, 6.0, 3.9)
add_text(slide, 0.9, 2.12, 5.4, 0.3, "Cómo se reparte el dinero", size=13, color=NAVY, bold=True)
rows = [
    ("Cliente paga", "$230", "Platillo $200 + envío $25 + servicio $5"),
    ("Restaurante recibe", "$195", "Subtotal $200 − cuota fija $5"),
    ("Repartidor recibe", "$25 + propina", "100% del envío"),
    ("Plataforma recibe", "$10", "$5 restaurante + $5 servicio"),
]
ry = 2.58
for label, value, note in rows:
    add_text(slide, 0.9, ry, 2.1, 0.25, label, size=9.5, color=GRAY)
    add_text(slide, 2.95, ry - 0.04, 1.6, 0.3, value, size=14, color=NAVY, bold=True)
    add_text(slide, 4.6, ry, 1.95, 0.45, note, size=8.5, color=GRAY, spacing=1.0)
    add_line(slide, 0.9, ry + 0.55, 6.3, ry + 0.55, color=LIGHT2, width=0.6)
    ry += 0.73
add_text(slide, 0.9, 5.45, 5.4, 0.25,
         "El envío adicional por km se suma al pago del repartidor.", size=8.5, color=GRAY_LIGHT, italic=True)

# Manual bar chart
base_y = 5.55
max_h = 2.9
add_text(slide, 7.1, 2.05, 5.2, 0.3, "Ingreso neto del restaurante", size=13, color=NAVY, bold=True)
add_text(slide, 7.1, 2.38, 5.2, 0.3, "Por un pedido de $200", size=9.5, color=GRAY)
add_line(slide, 7.35, base_y, 12.55, base_y, color=GRAY_LIGHT, width=1)
bar1_h = max_h * 150 / 200
bar2_h = max_h * 195 / 200
add_rect(slide, 7.9, base_y - bar1_h, 1.55, bar1_h, RGBColor(0xB7,0xC0,0xCF))
add_rect(slide, 10.35, base_y - bar2_h, 1.55, bar2_h, ORANGE)
add_text(slide, 7.55, base_y - bar1_h - 0.38, 2.3, 0.3, "$150", size=15, color=GRAY, bold=True, align=PP_ALIGN.CENTER)
add_text(slide, 10.0, base_y - bar2_h - 0.38, 2.3, 0.3, "$195", size=15, color=ORANGE_DARK, bold=True, align=PP_ALIGN.CENTER)
add_text(slide, 7.4, base_y + 0.12, 2.7, 0.45, "Marketplace\n25% de comisión", size=9, color=GRAY, align=PP_ALIGN.CENTER, spacing=1.0)
add_text(slide, 9.9, base_y + 0.12, 2.7, 0.45, "TuPedidoJR\ncuota fija", size=9, color=GRAY, align=PP_ALIGN.CENTER, spacing=1.0)
add_card(slide, 7.1, 6.05, 5.45, 0.65, fill=RGBColor(0xE8,0xF5,0xE9))
add_text(slide, 7.35, 6.16, 5.0, 0.4,
         "+$45 por pedido = +30% de ingreso neto", size=11.5, color=GREEN, bold=True)
add_text(slide, 7.1, 6.75, 5.45, 0.25,
         "La afiliación anual se recupera con ~12 pedidos de $200.", size=8.5, color=GRAY, italic=True)

# ---------------------------------------------------------------- Slide 8 restaurant costs
slide, y = add_slide_base(
    "$500 al año. Sin comisión por platillo.",
    kicker="Costos del restaurante", number=8,
    subtitle="Un costo fijo y predecible, con el paquete de lanzamiento incluido."
)
costs = [
    ("$500 / año", "Afiliación", "Mantiene la plataforma en línea y cubre el paquete de lanzamiento."),
    ("$5 / pedido", "Cuota fija", "Se descuenta solo en las cuentas del restaurante."),
    ("0%", "Comisión sobre alimentos", "El precio del menú es el que recibe el restaurante."),
]
for i, (value, label, note) in enumerate(costs):
    cy = 1.95 + i * 1.4
    add_card(slide, 0.62, cy, 5.0, 1.3)
    add_rect(slide, 0.8, cy, 0.06, 1.3, ORANGE)
    add_text(slide, 0.98, cy + 0.12, 4.45, 0.42, value, size=22, color=NAVY, bold=True)
    add_text(slide, 0.98, cy + 0.55, 4.45, 0.25, label, size=10.5, color=NAVY, bold=True)
    add_text(slide, 0.98, cy + 0.82, 4.45, 0.4, note, size=8.3, color=GRAY, spacing=1.0)
add_card(slide, 6.0, 1.95, 6.72, 4.1)
add_text(slide, 6.3, 2.12, 6.1, 0.3, "Qué incluye tu afiliación", size=14, color=NAVY, bold=True)
include = [
    "Menú digital personalizado",
    "Captura y fotografía del menú",
    "Volantes promocionales",
    "Acrílico con QR directo al menú",
    "Hosting, monitoreo y actualizaciones",
    "Capacitación y soporte local",
]
add_bullets(slide, 6.3, 2.62, 6.05, 3.3, include, size=12.5, spacing=10)
add_card(slide, 0.62, 6.25, 12.1, 0.52, fill=RGBColor(0xFF,0xF2,0xE8))
add_text(slide, 0.9, 6.35, 11.5, 0.3,
         "Sin inversión en desarrollo, hosting ni diseño web.", size=11, color=ORANGE_DARK, bold=True)

# ---------------------------------------------------------------- Slide 9 customer costs
slide, y = add_slide_base(
    "Precios claros antes de pagar",
    kicker="Costos del cliente", number=9,
    subtitle="El cliente conoce el desglose completo. Sin cargos sorpresa."
)
add_card(slide, 0.62, 1.95, 5.7, 3.9)
add_text(slide, 0.9, 2.12, 5.1, 0.3, "Fórmula del envío", size=13, color=NAVY, bold=True)
add_text(slide, 0.9, 2.55, 5.1, 0.35, "$25 base", size=22, color=ORANGE, bold=True)
add_text(slide, 2.55, 2.6, 3.4, 0.3, "hasta 1 km", size=10, color=GRAY)
add_text(slide, 0.9, 3.0, 5.1, 0.35, "+ $5 por km adicional", size=20, color=NAVY, bold=True)
add_text(slide, 0.9, 3.55, 5.1, 0.3, "+ $5 de cuota de servicio", size=15, color=NAVY, bold=True)
add_text(slide, 0.9, 3.95, 5.1, 0.3, "+ propina opcional (100% para el repartidor)", size=11, color=GRAY)
add_line(slide, 0.9, 4.45, 6.0, 4.45, color=LIGHT2, width=0.7)
add_text(slide, 0.9, 4.65, 5.1, 0.75,
         "El cliente ve el desglose antes de confirmar.\nRecoger en restaurante: sin envío ni propina.",
         size=10.5, color=GRAY, spacing=1.1)

# delivery table
d_rows = [["1 km", "$25"], ["3 km", "$35"], ["6 km", "$50"], ["8 km", "$60"], ["10 km", "$70"], ["12 km", "$80"]]
add_text(slide, 6.65, 2.0, 2.0, 0.3, "Distancia", size=10, color=GRAY, bold=True)
add_text(slide, 8.6, 2.0, 1.5, 0.3, "Envío", size=10, color=GRAY, bold=True)
add_line(slide, 6.65, 2.32, 10.4, 2.32, color=GRAY_LIGHT, width=0.8)
ry = 2.45
for km, fee in d_rows:
    add_text(slide, 6.65, ry, 2.0, 0.28, km, size=11, color=NAVY)
    add_text(slide, 8.6, ry, 1.5, 0.28, fee, size=11, color=NAVY, bold=True)
    add_line(slide, 6.65, ry + 0.38, 10.4, ry + 0.38, color=LIGHT2, width=0.5)
    ry += 0.48
add_card(slide, 6.35, 5.35, 6.35, 1.3, fill=RGBColor(0xFF,0xF2,0xE8), line=RGBColor(0xF7,0xD3,0xB5))
add_text(slide, 6.6, 5.5, 5.9, 0.3, "Pedidos de 8 km o más", size=12, color=ORANGE_DARK, bold=True)
add_text(slide, 6.6, 5.82, 5.9, 0.7,
         "Aviso antes de pagar. El restaurante no prepara hasta que un repartidor acepta. Si no hay repartidor en 30 min, se cancela y se reembolsa si pagó por transferencia.",
         size=9, color=GRAY, spacing=1.05)
add_text(slide, 0.62, 6.75, 12.0, 0.25,
         "Tarifas vigentes de la plataforma. El envío adicional por km se suma al pago del repartidor.",
         size=8, color=GRAY_LIGHT, italic=True)

# ---------------------------------------------------------------- Slide 10 delivery backed
slide, y = add_slide_base(
    "La plataforma se hace cargo de la entrega",
    kicker="Reparto respaldado", number=10,
    subtitle="Un pedido no se prepara hasta que hay quien lo entregue. Esa es la diferencia."
)
steps = [("1", "Pedido"), ("2", "Repartidor\nacepta"), ("3", "Restaurante\nprepara"), ("4", "Recoge"), ("5", "Entrega")]
sx = 0.62
for i, (num, label) in enumerate(steps):
    add_circle(slide, sx, 2.0, 0.55, ORANGE if i == 1 else NAVY)
    add_text(slide, sx, 2.1, 0.55, 0.22, num, size=12, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, sx - 0.25, 2.62, 1.05, 0.55, label, size=9.5, color=NAVY, bold=True,
             align=PP_ALIGN.CENTER, spacing=0.95)
    if i < 4:
        add_line(slide, sx + 0.6, 2.27, sx + 1.85, 2.27, color=ORANGE, width=1.8)
    sx += 2.42
add_card(slide, 0.62, 3.35, 12.1, 0.8, fill=RGBColor(0xFF,0xF2,0xE8))
add_text(slide, 0.9, 3.5, 11.5, 0.5,
         "En pedidos de 8 km o más, el restaurante no ve el pedido hasta que un repartidor lo acepta.",
         size=12.5, color=ORANGE_DARK, bold=True)
benefits = [
    ("Restaurante", "No desperdicia comida ni prepara pedidos sin salida."),
    ("Cliente", "Recibe aviso, seguimiento y reembolso cuando aplica."),
    ("Repartidor", "100% del envío y 100% de la propina. Km extra incluido."),
]
for i, (title, desc) in enumerate(benefits):
    cx = 0.62 + i * 4.08
    add_card(slide, cx, 4.45, 3.88, 1.55)
    add_text(slide, cx + 0.25, 4.62, 3.35, 0.3, title, size=12.5, color=NAVY, bold=True)
    add_text(slide, cx + 0.25, 5.02, 3.35, 0.8, desc, size=9.5, color=GRAY, spacing=1.05)
add_text(slide, 0.62, 6.3, 12.0, 0.35,
         "Seguimiento GPS, ETA por ruta y notificaciones push en cada etapa.",
         size=11, color=NAVY, bold=True)

# ---------------------------------------------------------------- Slide 11 menu
slide, y = add_slide_base(
    "Tu menú, con tu marca y tu QR",
    kicker="Menú digital", number=11,
    subtitle="No es un perfil dentro de un marketplace: es tu propia página, con tu marca y tu enlace."
)
# Phone mock
add_card(slide, 0.75, 1.95, 3.55, 4.75, fill=NAVY_DARK, radius=0.06)
add_rect(slide, 0.95, 2.15, 3.15, 4.35, WHITE, rounded=True, radius=0.03)
add_text(slide, 1.15, 2.32, 2.75, 0.25, "PruebaTortas", size=12, color=NAVY, bold=True)
add_text(slide, 1.15, 2.6, 2.75, 0.2, "Tortas · Bebidas · Postres", size=7.5, color=GRAY)
add_line(slide, 1.15, 2.85, 3.9, 2.85, color=LIGHT2, width=0.6)
menu_lines = [("Torta de Bisteck", "$50.00"), ("Torta de Jamón", "$45.00"), ("Refresco", "$20.00")]
my = 3.0
for name, price in menu_lines:
    add_rect(slide, 1.15, my, 0.5, 0.5, LIGHT2, rounded=True, radius=0.12)
    add_text(slide, 1.78, my, 1.55, 0.22, name, size=7.5, color=NAVY, bold=True)
    add_text(slide, 1.78, my + 0.22, 1.55, 0.2, price, size=7.5, color=GRAY)
    add_rect(slide, 3.25, my + 0.1, 0.3, 0.28, ORANGE, rounded=True, radius=0.2)
    add_text(slide, 3.25, my + 0.13, 0.3, 0.15, "+", size=9, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    my += 0.62
add_rect(slide, 1.15, 5.0, 0.85, 0.85, NAVY, rounded=True, radius=0.03)
add_text(slide, 1.15, 5.28, 0.85, 0.2, "QR", size=8, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
add_text(slide, 2.15, 5.12, 1.9, 0.6, "Escanea y pide\ndesde el menú", size=7.5, color=GRAY, spacing=1.0)
# bullets
add_text(slide, 4.75, 1.95, 7.9, 0.3, "Qué obtiene el restaurante", size=14, color=NAVY, bold=True)
menu_benefits = [
    "Página propia: /r/tu-restaurante",
    "Fotos, descripciones, categorías y opciones",
    "Horarios, disponibilidad y pedidos programados",
    "Entrega a domicilio o recoger en restaurante",
    "Notificaciones y panel de ganancias",
    "Sin depender de un marketplace para existir",
]
add_bullets(slide, 4.75, 2.45, 7.7, 3.1, menu_benefits, size=12.5, spacing=10)
add_card(slide, 4.75, 5.7, 7.95, 0.9, fill=RGBColor(0xE8,0xF5,0xE9))
add_text(slide, 5.0, 5.87, 7.5, 0.55,
         "Tu menú vive en tu propia URL y QR. No es un perfil dentro de otra plataforma.",
         size=11.5, color=GREEN, bold=True, spacing=1.05)

# ---------------------------------------------------------------- Slide 12 business model
slide, y = add_slide_base(
    "Ingresos recurrentes + ingresos por transacción",
    kicker="Modelo de negocio", number=12,
    subtitle="Un modelo simple de explicar y de auditar: afiliación anual y cuota fija por pedido."
)
revenue = [
    ("Afiliación anual", "$500", "Por restaurante. Cubre operación y materiales."),
    ("Cuota fija restaurante", "$5", "Por pedido. Sin porcentaje sobre alimentos."),
    ("Cuota de servicio cliente", "$5", "Por pedido. Visible en el desglose."),
    ("Envío", "Pass-through", "Va al repartidor; no es margen de la plataforma."),
]
for i, (label, value, note) in enumerate(revenue):
    col = i % 2
    row = i // 2
    cx = 0.62 + col * 6.15
    cy = 1.95 + row * 1.75
    add_card(slide, cx, cy, 5.95, 1.5)
    add_text(slide, cx + 0.25, cy + 0.18, 3.4, 0.3, label, size=10.5, color=GRAY, bold=True)
    add_text(slide, cx + 0.25, cy + 0.52, 2.6, 0.55, value, size=24, color=ORANGE, bold=True)
    add_text(slide, cx + 2.95, cy + 0.55, 2.75, 0.75, note, size=9, color=GRAY, spacing=1.05)
add_card(slide, 0.62, 5.55, 12.1, 1.2, fill=NAVY)
add_text(slide, 0.95, 5.72, 11.4, 0.3,
         "$10 de ingreso por pedido = $5 restaurante + $5 cliente", size=18, color=WHITE, bold=True)
add_text(slide, 0.95, 6.12, 11.4, 0.3,
         "A 500 pedidos/mes: $5,000/mes de ingreso transaccional, además de las afiliaciones anuales.",
         size=10.5, color=RGBColor(0xC9,0xD2,0xE3))
add_text(slide, 0.62, 6.85, 12.0, 0.2,
         "Escenario ilustrativo. No incluye impuestos ni costos de operación.",
         size=7.5, color=GRAY_LIGHT, italic=True)

# ---------------------------------------------------------------- Slide 13 investment
slide, y = add_slide_base(
    "$30,000 al año para mantener la plataforma en línea",
    kicker="Inversión y punto de equilibrio", number=13,
    subtitle="VPS, desarrollo, administración, monitoreo y soporte. Una estructura de costos baja y predecible."
)
break_even = [
    ("60 restaurantes", "$500 × 60 = $30,000/año", "La afiliación sola cubre la operación anual."),
    ("250 pedidos/mes", "$10 × 250 = $2,500/mes", "Equivale a $30,000 al año."),
    ("30 restaurantes + 250 pedidos/mes", "$15,000 + $30,000 = $45,000/año", "Cubre la operación y genera excedente."),
]
for i, (title, value, note) in enumerate(break_even):
    cx = 0.62 + i * 4.08
    add_card(slide, cx, 1.95, 3.88, 2.3)
    add_text(slide, cx + 0.25, 2.12, 3.35, 0.45, title, size=13, color=NAVY, bold=True, spacing=1.0)
    add_text(slide, cx + 0.25, 2.7, 3.35, 0.45, value, size=15, color=ORANGE_DARK, bold=True, spacing=1.0)
    add_text(slide, cx + 0.25, 3.3, 3.35, 0.75, note, size=9.5, color=GRAY, spacing=1.05)
add_card(slide, 0.62, 4.55, 7.4, 1.9, fill=LIGHT2)
add_text(slide, 0.9, 4.72, 6.8, 0.3, "Uso de fondos", size=13, color=NAVY, bold=True)
add_bullets(slide, 0.9, 5.12, 6.7, 1.2, [
    "Adquisición de restaurantes y materiales impresos",
    "Fotografía y producción de menús",
    "Soporte, monitoreo y mejora de la plataforma",
], size=10, spacing=5)
add_card(slide, 8.3, 4.55, 4.4, 1.9, fill=RGBColor(0xE8,0xF5,0xE9))
add_text(slide, 8.55, 4.72, 3.9, 0.3, "Palanca operativa", size=12, color=GREEN, bold=True)
add_text(slide, 8.55, 5.1, 3.85, 1.1,
         "Cada restaurante adicional y cada pedido adicional mejoran el margen, porque la infraestructura ya está construida.",
         size=10, color=GRAY, spacing=1.1)
add_text(slide, 0.62, 6.65, 12.0, 0.3,
         "Costo anual estimado de operación: $30,000 MXN. Cifras en pesos mexicanos.",
         size=8, color=GRAY_LIGHT, italic=True)

# ---------------------------------------------------------------- Slide 14 scalability
slide, y = add_slide_base(
    "Un modelo replicable, pueblo por pueblo",
    kicker="Escalabilidad", number=14,
    subtitle="La misma plataforma, el mismo playbook y un costo marginal bajo por nuevo restaurante."
)
add_text(slide, 0.62, 1.95, 5.6, 0.3, "Qué se replica", size=14, color=NAVY, bold=True)
add_bullets(slide, 0.62, 2.45, 5.6, 3.6, [
    "Alta de restaurante y menú digital",
    "Materiales y QR producidos localmente",
    "Repartidores independientes, sin flota propia",
    "Soporte en español y conocimiento local",
    "Cobros, liquidaciones y auditoría centralizados",
], size=11.5, spacing=9)
add_text(slide, 6.65, 1.95, 6.0, 0.3, "Ventaja competitiva local", size=14, color=NAVY, bold=True)
add_bullets(slide, 6.65, 2.45, 6.0, 3.6, [
    "Densidad de restaurantes y repartidores",
    "Relación directa con el negocio",
    "Tiempos de respuesta y soporte cercanos",
    "Precio fijo y transparente",
    "Marca local vs. marketplace global",
], size=11.5, spacing=9)
expansion = [
    ("Ciudad ancla", "Restaurantes + repartidores"),
    ("Comunidades", "Cobertura de hasta 12 km"),
    ("Nuevo municipio", "Mismo playbook, nueva plaza"),
]
for i, (title, desc) in enumerate(expansion):
    cx = 0.62 + i * 4.08
    add_card(slide, cx, 4.15, 3.88, 1.2)
    add_text(slide, cx + 0.25, 4.3, 3.35, 0.3, title, size=11.5, color=ORANGE_DARK, bold=True)
    add_text(slide, cx + 0.25, 4.65, 3.35, 0.45, desc, size=9.5, color=GRAY, spacing=1.0)
add_card(slide, 0.62, 5.7, 12.1, 0.75, fill=RGBColor(0xFF,0xF2,0xE8))
add_text(slide, 0.9, 5.87, 11.5, 0.4,
         "Más restaurantes = más pedidos; más pedidos = mejor densidad de reparto y menores tiempos.",
         size=12, color=ORANGE_DARK, bold=True)

# ---------------------------------------------------------------- Slide 15 risks
slide, y = add_slide_base(
    "Lo que puede salir mal y cómo lo controlamos",
    kicker="Riesgos y mitigación", number=15,
    subtitle="Un proyecto serio también explica sus riesgos. Estos son los principales y su respuesta."
)
risk_headers = ["Riesgo", "Mitigación"]
risk_rows = [
    ["Competencia de grandes marketplaces", "Costo fijo, trato local y reparto respaldado."],
    ["Adopción lenta de restaurantes", "Cuota baja, materiales y fotografía incluidos; piloto demostrable."],
    ["Oferta insuficiente de repartidores", "100% del envío + propina, bonos configurables y horarios flexibles."],
    ["Dependencia tecnológica", "VPS, respaldos, monitoreo y plataforma ya probada."],
    ["Fraude o incumplimiento", "Validación de pagos, reglas de cancelación y auditoría."],
]
add_table(slide, 0.62, 1.95, 12.1, 4.05, risk_headers, risk_rows,
          col_widths=[4.2, 7.9], font_size=10.2, row_height=0.66,
          center_columns=False)
add_card(slide, 0.62, 6.1, 12.1, 0.55, fill=RGBColor(0xE8,0xF5,0xE9))
add_text(slide, 0.9, 6.2, 11.5, 0.3,
         "La plataforma ya opera: el riesgo tecnológico está reducido; el foco es adopción y densidad.",
         size=10.5, color=GREEN, bold=True)

# ---------------------------------------------------------------- Slide 16 roadmap
slide, y = add_slide_base(
    "De piloto local a red regional",
    kicker="Siguientes pasos", number=16,
    subtitle="Una ruta por fases, con metas medibles y sin perder el foco local."
)
phases = [
    ("FASE 1 · CONSOLIDAR", "20–30 restaurantes", "Juventino Rosas. Medir tiempos, recompra y satisfacción."),
    ("FASE 2 · EXPANDIR", "60+ restaurantes", "Comunidades y municipios cercanos. Alianzas locales."),
    ("FASE 3 · ESCALAR", "150+ restaurantes", "Nuevos servicios: mandados, lealtad y promociones."),
]
for i, (phase, target, desc) in enumerate(phases):
    cx = 0.62 + i * 4.08
    add_card(slide, cx, 1.95, 3.88, 3.2)
    add_text(slide, cx + 0.25, 2.15, 3.35, 0.3, phase, size=10, color=ORANGE, bold=True)
    add_text(slide, cx + 0.25, 2.55, 3.35, 0.55, target, size=20, color=NAVY, bold=True)
    add_text(slide, cx + 0.25, 3.25, 3.35, 1.2, desc, size=10, color=GRAY, spacing=1.1)
    add_circle(slide, cx + 3.1, 4.55, 0.35, ORANGE)
    add_text(slide, cx + 3.1, 4.62, 0.35, 0.18, str(i + 1), size=9, color=WHITE,
             bold=True, align=PP_ALIGN.CENTER)
add_card(slide, 0.62, 5.5, 12.1, 1.15, fill=NAVY)
add_text(slide, 0.9, 5.65, 11.5, 0.3,
         "Meta: 60 restaurantes cubren la operación anual de $30,000.", size=16, color=WHITE, bold=True)
add_text(slide, 0.9, 6.05, 11.5, 0.3,
         "Cada restaurante adicional y cada pedido adicional son margen para reinvertir en crecimiento.",
         size=10.5, color=RGBColor(0xC9,0xD2,0xE3))

# ---------------------------------------------------------------- Slide 17 closing
slide = prs.slides.add_slide(BLANK)
add_rect(slide, 0, 0, 13.333, 7.5, NAVY_DARK)
add_rect(slide, 0, 0, 0.16, 7.5, ORANGE)
add_circle(slide, 10.7, -1.0, 3.3, RGBColor(0x24,0x3B,0x7A))
add_logo(slide, 0.85, 0.8, 5.0, on_dark=True)
add_text(slide, 0.85, 2.25, 11.4, 0.8,
         "Tecnología local, margen para el restaurante.",
         size=32, color=WHITE, bold=True)
add_text(slide, 0.85, 3.15, 11.0, 0.7,
         "TuPedidoJR ya está en operación. Buscamos restaurantes y aliados para escalar el modelo a nuevos municipios.",
         size=14, color=RGBColor(0xC9,0xD2,0xE3), spacing=1.1)
add_card(slide, 0.85, 4.2, 5.7, 1.55, fill=RGBColor(0x22,0x35,0x6E))
add_text(slide, 1.1, 4.38, 5.2, 0.3, "Para restaurantes", size=12, color=ORANGE, bold=True)
add_text(slide, 1.1, 4.75, 5.2, 0.8,
         "Afíliate por $500/año. Incluye menú, QR, volantes y fotografía.\nSin comisión por platillo.",
         size=11, color=WHITE, spacing=1.1)
add_card(slide, 6.8, 4.2, 5.7, 1.55, fill=RGBColor(0x22,0x35,0x6E))
add_text(slide, 7.05, 4.38, 5.2, 0.3, "Para inversionistas", size=12, color=ORANGE, bold=True)
add_text(slide, 7.05, 4.75, 5.2, 0.8,
         "Capital y alianzas para adquisición de restaurantes,\nmateriales y expansión regional.",
         size=11, color=WHITE, spacing=1.1)
add_text(slide, 0.85, 6.2, 11.0, 0.3,
         "WhatsApp 412 134 0765  ·  old.lodoman@gmail.com  ·  Juventino Rosas, Guanajuato",
         size=10.5, color=RGBColor(0xC9,0xD2,0xE3))
add_text(slide, 0.85, 6.65, 11.0, 0.3,
         "Gracias.", size=18, color=ORANGE, bold=True)

# Save
pptx_path = OUT / "TuPedidoJR_Propuesta_2026.pptx"
prs.save(str(pptx_path))
print(pptx_path)
