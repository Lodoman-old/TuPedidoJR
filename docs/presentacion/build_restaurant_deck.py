from pathlib import Path
from deck_lib import (
    OUT, NAVY, NAVY_DARK, ORANGE, ORANGE_DARK, LIGHT, LIGHT2, WHITE,
    GRAY, GRAY_LIGHT, GREEN, new_deck, blank, add_text, add_rect, add_circle,
    add_line, add_logo, add_footer, add_slide_base, add_card, add_kpi,
    add_bullets, add_table, PP_ALIGN, MSO_ANCHOR,
)
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor

prs = new_deck()

# ---------------------------------------------------------------- 1 Portada
slide = blank(prs)
add_rect(slide, 0, 0, 13.333, 7.5, NAVY_DARK)
add_rect(slide, 0, 0, 0.16, 7.5, ORANGE)
add_circle(slide, 10.9, -1.1, 3.4, RGBColor(0x24, 0x3B, 0x7A))
add_circle(slide, 11.6, 5.7, 2.2, RGBColor(0x22, 0x35, 0x6E))
add_text(slide, 0.85, 0.75, 6.0, 0.35, "PARA RESTAURANTES Y TIENDAS · 2026", size=11,
         color=ORANGE, bold=True)
add_logo(slide, 0.85, 1.3, 5.25, on_dark=True)
add_text(slide, 0.85, 3.05, 10.8, 0.9,
         "Tu menú, tu catálogo,\ntu margen.",
         size=40, color=WHITE, bold=True, spacing=0.95)
add_text(slide, 0.85, 4.35, 9.9, 0.75,
         "Menú digital, catálogo, pedidos y reparto local\nsin comisión por platillo.",
         size=17, color=RGBColor(0xC9, 0xD2, 0xE3), spacing=1.1)
chips = [("$500/año", "afiliación"), ("0%", "comisión por platillo"), ("QR + fotos", "incluidos")]
x = 0.85
for value, label in chips:
    add_card(slide, x, 5.45, 3.5, 0.78, fill=RGBColor(0x22, 0x35, 0x6E), radius=0.1)
    add_text(slide, x + 0.2, 5.53, 3.1, 0.35, value, size=16, color=ORANGE, bold=True)
    add_text(slide, x + 0.2, 5.88, 3.0, 0.25, label, size=9, color=RGBColor(0xC9, 0xD2, 0xE3))
    x += 3.75
add_text(slide, 0.85, 6.85, 10.0, 0.28,
         "Juventino Rosas, Guanajuato  ·  TuPedidoJR",
         size=9, color=RGBColor(0x9F, 0xAD, 0xC8))

# ---------------------------------------------------------------- 2 Problema
slide = add_slide_base(
    prs, "¿Cuánto te deja Uber Eats o DIDI por un pedido?",
    kicker="Lo que hoy pasa", number=2,
    subtitle="Vendes más, pero una parte importante de tu margen se va en comisiones. Y el cliente no es tuyo."
)
problems = [
    ("20–30%", "Comisión por pedido", "Se descuenta del valor de tus platillos, no solo de la ganancia."),
    ("Tú no eres dueño del cliente", "La relación vive en Uber Eats o DIDI", "No tienes su contacto ni un canal directo para volver a venderle."),
    ("Preparas sin saber si habrá repartidor", "Riesgo operativo", "Si nadie acepta el pedido, el alimento y el tiempo ya se invirtieron."),
]
for i, (value, label, note) in enumerate(problems):
    cx = 0.62 + i * 4.08
    add_card(slide, cx, 2.05, 3.92, 2.0)
    add_text(slide, cx + 0.28, 2.18, 3.35, 0.6, value, size=24 if i == 0 else 18,
             color=ORANGE, bold=True)
    add_text(slide, cx + 0.28, 2.9, 3.35, 0.4, label, size=11, color=NAVY, bold=True, spacing=1.0)
    add_text(slide, cx + 0.28, 3.32, 3.35, 0.55, note, size=9.3, color=GRAY, spacing=1.05)
add_card(slide, 0.62, 4.45, 12.1, 1.15, fill=RGBColor(0xFF, 0xF2, 0xE8), line=RGBColor(0xF7, 0xD3, 0xB5))
add_text(slide, 0.92, 4.63, 11.5, 0.34,
         "Un pedido de $200 con 25% de comisión te deja $150.", size=19, color=NAVY, bold=True)
add_text(slide, 0.92, 5.05, 11.5, 0.34,
         "Con TuPedidoJR te quedan $195. La diferencia son $45 por pedido.", size=13, color=GRAY)
add_text(slide, 0.62, 6.65, 12.0, 0.25,
         "Rango referencial de comisiones de Uber Eats y DIDI en México. Verifica sus términos vigentes.",
         size=8, color=GRAY_LIGHT, italic=True)

# ---------------------------------------------------------------- 3 Solución
slide = add_slide_base(
    prs, "TuPedidoJR: tu canal directo de pedidos",
    kicker="La propuesta", number=3,
    subtitle="Tú pones el precio y la sazón. Nosotros ponemos la tecnología, el menú y el respaldo del reparto."
)
solutions = [
    ("Menú propio + QR", "Tu página con fotos, categorías, precios, opciones y horarios."),
    ("Pedidos y pagos", "Efectivo o transferencia. El cliente ve el desglose antes de pagar."),
    ("Reparto local respaldado", "La plataforma coordina y responde por la entrega."),
    ("Costo fijo y transparente", "$500 al año + $5 por pedido. Sin comisión porcentual."),
]
for i, (title, desc) in enumerate(solutions):
    col = i % 2
    row = i // 2
    cx = 0.62 + col * 6.15
    cy = 2.0 + row * 2.0
    add_card(slide, cx, cy, 5.95, 1.7)
    add_circle(slide, cx + 0.25, cy + 0.25, 0.42, ORANGE)
    add_text(slide, cx + 0.25, cy + 0.34, 0.42, 0.2, str(i + 1), size=12,
             color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, cx + 0.85, cy + 0.22, 4.8, 0.34, title, size=14, color=NAVY, bold=True)
    add_text(slide, cx + 0.85, cy + 0.66, 4.75, 0.78, desc, size=10.5, color=GRAY, spacing=1.08)
add_text(slide, 0.62, 6.3, 12.0, 0.4,
         "Sin comisión por platillo. Sin página web que mantener. Sin perder tu marca.",
         size=13, color=ORANGE_DARK, bold=True)

# ---------------------------------------------------------------- 4 Comparativo
slide = add_slide_base(
    prs, "TuPedidoJR vs. Uber Eats y DIDI",
    kicker="Comparativo directo", number=4,
    subtitle="La diferencia no es solo el costo: es quién controla tu menú, tu cliente y tu operación."
)
headers = ["", "TuPedidoJR", "Uber Eats / DIDI"]
rows = [
    ["Costo del restaurante", "$500/año + $5 por pedido", "Comisión de 20–30% por pedido"],
    ["Comisión sobre alimentos", "0%", "20–30% del valor del platillo"],
    ["Menú y marca", "Página propia con URL y QR", "Perfil dentro de Uber Eats o DIDI"],
    ["Material físico", "Volantes, acrílico y fotografía incluidos", "No incluido o con costo adicional"],
    ["Relación con el cliente", "Canal directo del restaurante", "El cliente es de Uber Eats o DIDI"],
    ["Respaldo de entrega", "Pedidos lejanos se retienen hasta tener repartidor", "Asignación de la plataforma"],
    ["Pago al repartidor", "100% envío + 100% propina", "Modelo variable"],
    ["¿Quién es dueño de tu menú?", "Tú", "La plataforma"],
]
add_table(slide, 0.62, 1.95, 12.1, 4.8, headers, rows,
          col_widths=[2.55, 4.65, 4.9], font_size=9.3, row_height=0.5)
add_text(slide, 0.62, 6.8, 12.0, 0.25,
         "Comisiones de Uber Eats y DIDI: referencia de mercado. Verifica sus términos vigentes.",
         size=8, color=GRAY_LIGHT, italic=True)

# ---------------------------------------------------------------- 5 Ejemplo
slide = add_slide_base(
    prs, "Un pedido de $200, explicado",
    kicker="Cuánto te queda", number=5,
    subtitle="Ejemplo con reparto de la plataforma y envío base de 1 km."
)
add_card(slide, 0.62, 1.95, 6.0, 3.9)
add_text(slide, 0.9, 2.12, 5.4, 0.3, "Cómo se reparte el dinero", size=13, color=NAVY, bold=True)
rows = [
    ("Cliente paga", "$230", "Platillo $200 + envío $25 + servicio $5"),
    ("Tú recibes", "$195", "Subtotal $200 − cuota fija $5"),
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
         "El envío adicional por km se suma al pago del repartidor.", size=8.5,
         color=GRAY_LIGHT, italic=True)

base_y = 5.55
max_h = 2.9
add_text(slide, 7.1, 2.05, 5.2, 0.3, "Lo que te queda por el mismo pedido", size=13, color=NAVY, bold=True)
add_text(slide, 7.1, 2.38, 5.2, 0.3, "Pedido de $200", size=9.5, color=GRAY)
add_line(slide, 7.35, base_y, 12.55, base_y, color=GRAY_LIGHT, width=1)
bar1_h = max_h * 150 / 200
bar2_h = max_h * 195 / 200
add_rect(slide, 7.9, base_y - bar1_h, 1.55, bar1_h, RGBColor(0xB7, 0xC0, 0xCF))
add_rect(slide, 10.35, base_y - bar2_h, 1.55, bar2_h, ORANGE)
add_text(slide, 7.55, base_y - bar1_h - 0.38, 2.3, 0.3, "$150", size=15, color=GRAY, bold=True, align=PP_ALIGN.CENTER)
add_text(slide, 10.0, base_y - bar2_h - 0.38, 2.3, 0.3, "$195", size=15, color=ORANGE_DARK, bold=True, align=PP_ALIGN.CENTER)
add_text(slide, 7.4, base_y + 0.12, 2.7, 0.45, "Uber Eats / DIDI\n25% de comisión", size=9, color=GRAY, align=PP_ALIGN.CENTER, spacing=1.0)
add_text(slide, 9.9, base_y + 0.12, 2.7, 0.45, "TuPedidoJR\ncuota fija", size=9, color=GRAY, align=PP_ALIGN.CENTER, spacing=1.0)
add_card(slide, 7.1, 6.05, 5.45, 0.65, fill=RGBColor(0xE8, 0xF5, 0xE9))
add_text(slide, 7.35, 6.16, 5.0, 0.4,
         "+$45 por pedido = +30% de ingreso neto", size=11.5, color=GREEN, bold=True)
add_text(slide, 7.1, 6.75, 5.45, 0.25,
         "Recuperas la afiliación anual con ~12 pedidos de $200.", size=8.5, color=GRAY, italic=True)

# ---------------------------------------------------------------- 6 Costos
slide = add_slide_base(
    prs, "$500 al año. Sin comisión por platillo.",
    kicker="Tu inversión", number=6,
    subtitle="Un costo fijo y predecible, con el paquete de lanzamiento incluido."
)
costs = [
    ("$500 / año", "Afiliación", "Mantiene la plataforma en línea y cubre el paquete de lanzamiento."),
    ("$5 / pedido", "Cuota fija", "Se descuenta solo en tus cuentas, nunca en el precio del cliente."),
    ("0%", "Comisión sobre alimentos", "El precio de tu menú es el que recibe el restaurante."),
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
add_bullets(slide, 6.3, 2.62, 6.05, 3.2, include, size=12.5, spacing=10)
add_card(slide, 0.62, 6.25, 12.1, 0.52, fill=RGBColor(0xFF, 0xF2, 0xE8))
add_text(slide, 0.9, 6.35, 11.5, 0.3,
         "Sin inversión en desarrollo, hosting ni diseño web.", size=11,
         color=ORANGE_DARK, bold=True)

# ---------------------------------------------------------------- 7 Menú
slide = add_slide_base(
    prs, "Tu menú, con tu marca y tu QR",
    kicker="Menú digital", number=7,
    subtitle="No es un perfil dentro de Uber Eats o DIDI: es tu propia página, con tu enlace y tu marca."
)
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
add_text(slide, 2.15, 5.12, 1.9, 0.6, "Escanea y pide\ndesde tu menú", size=7.5, color=GRAY, spacing=1.0)
add_text(slide, 4.75, 1.95, 7.9, 0.3, "Qué obtiene tu restaurante", size=14, color=NAVY, bold=True)
menu_benefits = [
    "Página propia: /r/tu-restaurante",
    "Fotos, descripciones, categorías y opciones",
    "Horarios, disponibilidad y pedidos programados",
    "Entrega a domicilio o recoger en restaurante",
    "Notificaciones y panel de ganancias",
    "Tu menú no depende de Uber Eats o DIDI para existir",
]
add_bullets(slide, 4.75, 2.45, 7.7, 3.1, menu_benefits, size=12.5, spacing=10)
add_card(slide, 4.75, 5.7, 7.95, 0.9, fill=RGBColor(0xE8, 0xF5, 0xE9))
add_text(slide, 5.0, 5.87, 7.5, 0.55,
         "Tu menú vive en tu propia URL y QR. No es un perfil dentro de otra plataforma.",
         size=11.5, color=GREEN, bold=True, spacing=1.05)

# ---------------------------------------------------------------- 8 Reparto
slide = add_slide_base(
    prs, "El envío lo respalda TuPedidoJR",
    kicker="Reparto", number=8,
    subtitle="Tú no sales a buscar repartidor ni adelantas el envío. La plataforma coordina la entrega."
)
steps = [("1", "Pedido"), ("2", "Repartidor\nacepta"), ("3", "Tú\npreparas"), ("4", "Recoge"), ("5", "Entrega")]
sx = 0.62
for i, (num, label) in enumerate(steps):
    add_circle(slide, sx, 2.0, 0.55, ORANGE if i == 1 else NAVY)
    add_text(slide, sx, 2.1, 0.55, 0.22, num, size=12, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, sx - 0.25, 2.62, 1.05, 0.55, label, size=9.5, color=NAVY, bold=True,
             align=PP_ALIGN.CENTER, spacing=0.95)
    if i < 4:
        add_line(slide, sx + 0.6, 2.27, sx + 1.85, 2.27, color=ORANGE, width=1.8)
    sx += 2.42
add_card(slide, 0.62, 3.35, 12.1, 0.8, fill=RGBColor(0xFF, 0xF2, 0xE8))
add_text(slide, 0.9, 3.5, 11.5, 0.5,
         "En pedidos de 8 km o más, no preparas hasta que un repartidor acepta.",
         size=12.5, color=ORANGE_DARK, bold=True)
benefits = [
    ("Tú", "No gastas ingredientes en un pedido que podría quedarse sin repartidor."),
    ("Cliente", "Recibe aviso, seguimiento y reembolso cuando aplica."),
    ("Repartidor", "100% del envío y 100% de la propina. Km extra incluido."),
]
for i, (title, desc) in enumerate(benefits):
    cx = 0.62 + i * 4.08
    add_card(slide, cx, 4.45, 3.88, 1.55)
    add_text(slide, cx + 0.25, 4.62, 3.35, 0.3, title, size=12.5, color=NAVY, bold=True)
    add_text(slide, cx + 0.25, 5.02, 3.35, 0.8, desc, size=9.5, color=GRAY, spacing=1.05)
add_text(slide, 0.62, 6.3, 12.0, 0.35,
         "Si no hay repartidor en 30 minutos, el pedido se cancela automáticamente.",
         size=11, color=NAVY, bold=True)

# ---------------------------------------------------------------- 9 Ganancias
slide = add_slide_base(
    prs, "Cuentas claras, todos los días",
    kicker="Tus ganancias", number=9,
    subtitle="Sabes cuánto vendiste, cuánto se descontó y cuánto vas a recibir."
)
add_card(slide, 0.62, 1.95, 6.0, 4.1)
add_text(slide, 0.9, 2.12, 5.4, 0.3, "Ejemplo de un pedido", size=13, color=NAVY, bold=True)
earnings = [
    ("Subtotal del platillo", "$200.00"),
    ("Cuota fija por pedido", "- $5.00"),
    ("Ganancia neta", "$195.00"),
    ("Envío (lo paga el cliente)", "$25.00"),
    ("Propina (opcional)", "100% repartidor"),
]
ry = 2.65
for label, value in earnings:
    add_text(slide, 0.9, ry, 3.9, 0.28, label, size=10.5, color=GRAY)
    add_text(slide, 4.8, ry, 1.5, 0.28, value, size=11.5, color=NAVY, bold=True, align=PP_ALIGN.RIGHT)
    add_line(slide, 0.9, ry + 0.42, 6.3, ry + 0.42, color=LIGHT2, width=0.5)
    ry += 0.55
add_card(slide, 6.9, 1.95, 5.8, 4.1)
add_text(slide, 7.15, 2.12, 5.3, 0.3, "Lo que puedes consultar", size=13, color=NAVY, bold=True)
add_bullets(slide, 7.15, 2.62, 5.2, 3.1, [
    "Ventas del día y del periodo",
    "Cuota fija descontada por pedido",
    "Ganancia neta y liquidaciones",
    "Historial de pedidos y cancelaciones",
    "Estado de cada entrega en tiempo real",
    "Soporte local por WhatsApp",
], size=11, spacing=8)
add_card(slide, 0.62, 6.2, 12.1, 0.55, fill=RGBColor(0xE8, 0xF5, 0xE9))
add_text(slide, 0.9, 6.32, 11.5, 0.3,
         "Sin porcentajes escondidos. La cuota fija se ve en tu cuenta, no en el precio del cliente.",
         size=10.5, color=GREEN, bold=True)

# ---------------------------------------------------------------- 10 Onboarding
slide = add_slide_base(
    prs, "Así empezamos en 5 pasos",
    kicker="Alta y lanzamiento", number=10,
    subtitle="Nosotros nos encargamos de la parte técnica y de los materiales. Tú te enfocas en cocinar."
)
steps = [
    ("1", "Afiliación y alta", "Firmamos y registramos tu restaurante."),
    ("2", "Fotografía y menú", "Capturamos tus platillos y armamos el menú digital."),
    ("3", "QR y materiales", "Diseñamos tu acrílico, volantes y enlace."),
    ("4", "Capacitación", "Te enseñamos a confirmar pedidos y actualizar disponibilidad."),
    ("5", "Primer pedido", "Publicamos tu menú y empezamos a recibir pedidos."),
]
for i, (num, title, desc) in enumerate(steps):
    cx = 0.62 + i * 2.47
    add_card(slide, cx, 1.95, 2.27, 3.35)
    add_circle(slide, cx + 0.2, 2.15, 0.45, ORANGE)
    add_text(slide, cx + 0.2, 2.26, 0.45, 0.2, num, size=10, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, cx + 0.2, 2.78, 1.9, 0.55, title, size=11.5, color=NAVY, bold=True, spacing=1.0)
    add_text(slide, cx + 0.2, 3.42, 1.9, 1.2, desc, size=9.5, color=GRAY, spacing=1.05)
add_card(slide, 0.62, 5.65, 12.1, 0.95, fill=RGBColor(0xFF, 0xF2, 0xE8))
add_text(slide, 0.9, 5.82, 11.5, 0.6,
         "Todo el paquete está incluido en la afiliación anual. Coordinamos contigo la fecha de arranque.",
         size=11.5, color=ORANGE_DARK, bold=True, spacing=1.05)

# ---------------------------------------------------------------- 11 Tipos de envío
slide = add_slide_base(
    prs, "Un ecosistema: restaurantes, tiendas y mandados",
    kicker="Tipos de envío", number=11,
    subtitle="TuPedidoJR no es solo comida. Conecta negocios locales con clientes y resuelve compras que no están en catálogo."
)
channels = [
    ("Catálogo", "Restaurante o tienda",
     "El cliente pide desde el catálogo, paga productos + envío + $5 de servicio y el negocio prepara el pedido.",
     "Comisión del negocio: $5 por pedido."),
    ("Solicitud", "Producto fuera de catálogo",
     "El cliente describe el producto; la tienda cotiza, el cliente confirma y se genera un pedido normal.",
     "Mismos cargos: $5 cliente + $5 tienda + envío."),
    ("Mandado abierto", "Compra asistida",
     "El cliente describe lo que necesita y un repartidor lo compra en cualquier negocio con presupuesto y comprobante.",
     "Cargo por riesgo: $15. Envío real por km."),
]
for i, (tag, title, desc, note) in enumerate(channels):
    cx = 0.62 + i * 4.08
    add_card(slide, cx, 2.0, 3.88, 3.55)
    add_rect(slide, cx + 0.25, 2.2, 1.35, 0.3, ORANGE if i < 2 else NAVY, rounded=True, radius=0.3)
    add_text(slide, cx + 0.25, 2.25, 1.35, 0.2, tag, size=8.5, color=WHITE, bold=True,
             align=PP_ALIGN.CENTER)
    add_text(slide, cx + 0.25, 2.65, 3.35, 0.35, title, size=14, color=NAVY, bold=True)
    add_text(slide, cx + 0.25, 3.1, 3.35, 1.15, desc, size=9.8, color=GRAY, spacing=1.08)
    add_line(slide, cx + 0.25, 4.35, cx + 3.6, 4.35, color=LIGHT2, width=0.6)
    add_text(slide, cx + 0.25, 4.5, 3.35, 0.55, note, size=9.2, color=ORANGE_DARK,
             bold=True, spacing=1.05)
add_card(slide, 0.62, 5.85, 12.1, 0.8, fill=RGBColor(0xE8, 0xF5, 0xE9))
add_text(slide, 0.9, 6.02, 11.5, 0.45,
         "Una tienda puede empezar sin catálogo, recibir solicitudes y publicar después sus productos principales.",
         size=11.5, color=GREEN, bold=True)

# ---------------------------------------------------------------- 12 Procesos
slide = add_slide_base(
    prs, "Cómo se mueve cada pedido",
    kicker="Procesos claros", number=12,
    subtitle="Cada flujo tiene un responsable, un comprobante y un cobro transparente."
)
flows = [
    ("Catálogo", [
        "Cliente pide y paga",
        "Negocio confirma y prepara",
        "Repartidor recoge",
        "Cliente recibe",
    ], "Productos + envío + $5 cliente.\nNegocio: $5 de comisión."),
    ("Solicitud a tienda", [
        "Cliente describe el producto",
        "Tienda cotiza disponibilidad y precio",
        "Cliente confirma",
        "Se genera un pedido normal",
    ], "Producto cotizado + envío + $5.\nNegocio: $5 de comisión."),
    ("Mandado abierto", [
        "Cliente describe y pone presupuesto",
        "Repartidor acepta",
        "Confirma tienda y envío real",
        "Compra, sube ticket y entrega",
    ], "Compra + envío real + $15 de riesgo.\nPrepago desde $1,000 sin historial."),
]
for i, (title, steps, fees) in enumerate(flows):
    cx = 0.62 + i * 4.08
    add_card(slide, cx, 2.0, 3.88, 3.55)
    add_text(slide, cx + 0.25, 2.18, 3.35, 0.3, title, size=14, color=NAVY, bold=True)
    sy = 2.68
    for idx, step in enumerate(steps):
        add_circle(slide, cx + 0.25, sy, 0.3, ORANGE if idx == 0 else NAVY)
        add_text(slide, cx + 0.25, sy + 0.055, 0.3, 0.18, str(idx + 1), size=7.5,
                 color=WHITE, bold=True, align=PP_ALIGN.CENTER)
        add_text(slide, cx + 0.68, sy - 0.01, 2.9, 0.32, step, size=9.3, color=GRAY, spacing=1.0)
        sy += 0.43
    add_line(slide, cx + 0.25, 4.45, cx + 3.6, 4.45, color=LIGHT2, width=0.6)
    add_text(slide, cx + 0.25, 4.58, 3.35, 0.7, fees, size=8.8, color=ORANGE_DARK,
             bold=True, spacing=1.05)
add_card(slide, 0.62, 5.85, 12.1, 0.8, fill=RGBColor(0xFF, 0xF2, 0xE8))
add_text(slide, 0.9, 6.02, 11.5, 0.45,
         "En mandados abiertos el envío se estima y se ajusta con la distancia real tienda → cliente.",
         size=11.5, color=ORANGE_DARK, bold=True)

# ---------------------------------------------------------------- 13 FAQ
slide = add_slide_base(
    prs, "Preguntas frecuentes",
    kicker="Antes de decidir", number=13,
    subtitle="Lo que más nos preguntan los restaurantes y tiendas."
)
faqs = [
    ("¿Solo es para restaurantes?", "No. También tiendas con catálogo, farmacias, abarrotes y mandados abiertos."),
    ("¿Necesito subir todo mi catálogo?", "No. Puedes empezar con tus productos principales y recibir solicitudes de lo que falte."),
    ("¿Quién cobra el envío?", "El cliente. El repartidor recibe el 100% del envío."),
    ("¿Puedo seguir usando Uber Eats o DIDI?", "Sí. TuPedidoJR es un canal adicional, no te obliga a dejar los demás."),
    ("¿Qué pasa si no hay repartidor?", "En pedidos de 8 km o más no preparas hasta que alguien acepte. Si no ocurre en 30 min, se cancela."),
    ("¿Puedo cambiar precios y disponibilidad?", "Sí, desde tu panel cuando quieras."),
]
for i, (q, a) in enumerate(faqs):
    col = i % 2
    row = i // 2
    cx = 0.62 + col * 6.15
    cy = 1.95 + row * 1.45
    add_card(slide, cx, cy, 5.95, 1.25)
    add_text(slide, cx + 0.25, cy + 0.15, 5.4, 0.3, q, size=11, color=NAVY, bold=True)
    add_text(slide, cx + 0.25, cy + 0.52, 5.4, 0.6, a, size=9.5, color=GRAY, spacing=1.05)
add_card(slide, 0.62, 6.2, 12.1, 0.55, fill=RGBColor(0xFF, 0xF2, 0xE8))
add_text(slide, 0.9, 6.32, 11.5, 0.3,
         "¿Otra duda? WhatsApp 412 134 0765  ·  old.lodoman@gmail.com",
         size=10.5, color=ORANGE_DARK, bold=True)

# ---------------------------------------------------------------- 12 CTA
slide = blank(prs)
add_rect(slide, 0, 0, 13.333, 7.5, NAVY_DARK)
add_rect(slide, 0, 0, 0.16, 7.5, ORANGE)
add_circle(slide, 10.7, -1.0, 3.3, RGBColor(0x24, 0x3B, 0x7A))
add_logo(slide, 0.85, 0.8, 5.0, on_dark=True)
add_text(slide, 0.85, 2.2, 11.4, 0.8,
         "Haz que tu negocio trabaje para ti.",
         size=34, color=WHITE, bold=True)
add_text(slide, 0.85, 3.05, 11.0, 0.7,
         "Afíliate por $500 al año. Incluye menú o catálogo digital, QR, volantes y fotografía.\nSin comisión por platillo.",
         size=16, color=RGBColor(0xC9, 0xD2, 0xE3), spacing=1.15)
add_card(slide, 0.85, 4.25, 5.7, 1.45, fill=RGBColor(0x22, 0x35, 0x6E))
add_text(slide, 1.1, 4.42, 5.2, 0.3, "Agenda una visita", size=12, color=ORANGE, bold=True)
add_text(slide, 1.1, 4.78, 5.2, 0.7,
         "Te llevamos el menú digital y el acrílico\na tu restaurante.",
         size=11, color=WHITE, spacing=1.1)
add_card(slide, 6.8, 4.25, 5.7, 1.45, fill=RGBColor(0x22, 0x35, 0x6E))
add_text(slide, 7.05, 4.42, 5.2, 0.3, "Contacto", size=12, color=ORANGE, bold=True)
add_text(slide, 7.05, 4.78, 5.2, 0.7,
         "WhatsApp 412 134 0765\nold.lodoman@gmail.com",
         size=11, color=WHITE, spacing=1.1)
add_text(slide, 0.85, 6.2, 11.0, 0.3,
         "Juventino Rosas, Guanajuato  ·  TuPedidoJR",
         size=10.5, color=RGBColor(0xC9, 0xD2, 0xE3))
add_text(slide, 0.85, 6.65, 11.0, 0.3, "Gracias.", size=18, color=ORANGE, bold=True)

path = OUT / "TuPedidoJR_Restaurantes_2026.pptx"
prs.save(str(path))
print(path)
