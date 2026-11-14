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
add_text(slide, 0.85, 0.75, 5.0, 0.35, "PARA REPARTIDORES · 2026", size=11,
         color=ORANGE, bold=True)
add_logo(slide, 0.85, 1.3, 5.25, on_dark=True)
add_text(slide, 0.85, 3.05, 11.0, 0.9,
         "Reparte con TuPedidoJR.\nTú decides cuándo.",
         size=38, color=WHITE, bold=True, spacing=0.95)
add_text(slide, 0.85, 4.4, 9.8, 0.7,
         "Pedidos locales, 100% del envío y 100% de la propina.",
         size=17, color=RGBColor(0xC9, 0xD2, 0xE3))
chips = [("100%", "del envío"), ("100%", "de la propina"), ("Tú", "decides tu horario")]
x = 0.85
for value, label in chips:
    add_card(slide, x, 5.45, 3.5, 0.78, fill=RGBColor(0x22, 0x35, 0x6E), radius=0.1)
    add_text(slide, x + 0.2, 5.53, 3.1, 0.35, value, size=18, color=ORANGE, bold=True)
    add_text(slide, x + 0.2, 5.88, 3.0, 0.25, label, size=9, color=RGBColor(0xC9, 0xD2, 0xE3))
    x += 3.75
add_text(slide, 0.85, 6.85, 10.0, 0.28,
         "Juventino Rosas, Guanajuato  ·  TuPedidoJR",
         size=9, color=RGBColor(0x9F, 0xAD, 0xC8))

# ---------------------------------------------------------------- 2 Beneficios
slide = add_slide_base(
    prs, "¿Por qué repartir con TuPedidoJR?",
    kicker="La propuesta", number=2,
    subtitle="Menos complicaciones, más control sobre tu tiempo y tus ingresos."
)
benefits = [
    ("100% del envío", "No descontamos comisión de tu envío. Lo que ganas por la entrega es tuyo."),
    ("100% de la propina", "La propina del cliente es completa para ti."),
    ("Tú decides", "Conéctate cuando quieras. Sin horario fijo ni cuota de entrada."),
    ("Pedidos locales", "Distancias claras, soporte cercano y una operación de tu ciudad."),
]
for i, (title, desc) in enumerate(benefits):
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
         "Tu vehículo, tu teléfono, tus reglas. Nosotros ponemos los pedidos.",
         size=13, color=ORANGE_DARK, bold=True)

# ---------------------------------------------------------------- 3 Ganancias
slide = add_slide_base(
    prs, "Cuánto puedes ganar por envío",
    kicker="Tus ingresos", number=3,
    subtitle="El envío se paga completo y la propina también. Así de claro."
)
add_card(slide, 0.62, 1.95, 5.9, 3.9)
add_text(slide, 0.9, 2.12, 5.3, 0.3, "Cómo se calcula tu envío", size=13, color=NAVY, bold=True)
add_text(slide, 0.9, 2.6, 5.2, 0.35, "$25 base", size=24, color=ORANGE, bold=True)
add_text(slide, 2.55, 2.66, 3.4, 0.3, "hasta 1 km", size=10, color=GRAY)
add_text(slide, 0.9, 3.08, 5.2, 0.35, "+ $5 por km adicional", size=20, color=NAVY, bold=True)
add_text(slide, 0.9, 3.6, 5.2, 0.35, "+ 100% de la propina", size=17, color=GREEN, bold=True)
add_text(slide, 0.9, 4.05, 5.2, 0.3, "Máximo de entrega: 12 km", size=10, color=GRAY)
add_line(slide, 0.9, 4.5, 6.0, 4.5, color=LIGHT2, width=0.7)
add_text(slide, 0.9, 4.7, 5.3, 0.8,
         "Ejemplo ilustrativo: 10 envíos de $35 = $350 + propinas.\nLos ingresos dependen de la demanda, tu disponibilidad y la zona.",
         size=9.8, color=GRAY, spacing=1.1)

d_rows = [["1 km", "$25"], ["3 km", "$35"], ["6 km", "$50"], ["8 km", "$60"], ["10 km", "$70"], ["12 km", "$80"]]
add_text(slide, 6.9, 2.0, 2.2, 0.3, "Distancia", size=10, color=GRAY, bold=True)
add_text(slide, 9.0, 2.0, 1.2, 0.3, "Envío", size=10, color=GRAY, bold=True)
add_line(slide, 6.9, 2.32, 10.7, 2.32, color=GRAY_LIGHT, width=0.8)
ry = 2.45
for km, fee in d_rows:
    add_text(slide, 6.9, ry, 2.2, 0.28, km, size=11, color=NAVY)
    add_text(slide, 9.0, ry, 1.2, 0.28, fee, size=11, color=NAVY, bold=True)
    add_line(slide, 6.9, ry + 0.38, 10.7, ry + 0.38, color=LIGHT2, width=0.5)
    ry += 0.48
add_card(slide, 6.55, 5.4, 6.15, 1.2, fill=RGBColor(0xE8, 0xF5, 0xE9))
add_text(slide, 6.8, 5.55, 5.7, 0.3, "Sin comisión sobre tu envío", size=11.5, color=GREEN, bold=True)
add_text(slide, 6.8, 5.9, 5.7, 0.5,
         "El envío y la propina son tuyos. TuPedidoJR no se queda con un porcentaje de tu entrega.",
         size=9.5, color=GRAY, spacing=1.05)
add_text(slide, 0.62, 6.75, 12.0, 0.25,
         "Tarifas vigentes de la plataforma. El km extra se suma al pago del repartidor.",
         size=8, color=GRAY_LIGHT, italic=True)

# ---------------------------------------------------------------- 4 Día
slide = add_slide_base(
    prs, "Así se ve tu día",
    kicker="Cómo funciona", number=4,
    subtitle="Tú controlas tu disponibilidad. La app te muestra lo necesario antes de aceptar."
)
steps = [("1", "Conéctate"), ("2", "Mira pedidos"), ("3", "Acepta"), ("4", "Recoge"), ("5", "Entrega")]
sx = 0.62
for i, (num, label) in enumerate(steps):
    add_circle(slide, sx, 2.0, 0.55, ORANGE if i == 2 else NAVY)
    add_text(slide, sx, 2.1, 0.55, 0.22, num, size=12, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, sx - 0.25, 2.62, 1.05, 0.55, label, size=9.5, color=NAVY, bold=True,
             align=PP_ALIGN.CENTER, spacing=0.95)
    if i < 4:
        add_line(slide, sx + 0.6, 2.27, sx + 1.85, 2.27, color=ORANGE, width=1.8)
    sx += 2.42
add_card(slide, 0.62, 3.35, 12.1, 0.8, fill=RGBColor(0xFF, 0xF2, 0xE8))
add_text(slide, 0.9, 3.5, 11.5, 0.5,
         "Antes de aceptar ves distancia, tiempo y ganancia. Tú decides si lo tomas.",
         size=12.5, color=ORANGE_DARK, bold=True)
benefits = [
    ("Disponibilidad", "Actívate cuando quieras y desconéctate cuando termines."),
    ("Pedidos claros", "Distancia, restaurante y ganancia antes de aceptar."),
    ("Soporte local", "Si algo pasa, el equipo te ayuda por WhatsApp."),
]
for i, (title, desc) in enumerate(benefits):
    cx = 0.62 + i * 4.08
    add_card(slide, cx, 4.45, 3.88, 1.55)
    add_text(slide, cx + 0.25, 4.62, 3.35, 0.3, title, size=12.5, color=NAVY, bold=True)
    add_text(slide, cx + 0.25, 5.02, 3.35, 0.8, desc, size=9.5, color=GRAY, spacing=1.05)
add_text(slide, 0.62, 6.3, 12.0, 0.35,
         "No tienes que aceptar todos los pedidos: elige los que te convengan.",
         size=11, color=NAVY, bold=True)

# ---------------------------------------------------------------- 5 App
slide = add_slide_base(
    prs, "Tu app de repartidor",
    kicker="Herramientas", number=5,
    subtitle="Todo lo que necesitas para repartir y cobrar, desde tu teléfono."
)
features = [
    ("APP", "Pedidos disponibles", "Distancia, tiempo y ganancia antes de aceptar."),
    ("GPS", "Ubicación y ETA", "La app comparte tu ubicación y calcula el tiempo de llegada."),
    ("$", "Ganancias", "Envíos, propinas y deuda en un solo lugar."),
    ("ON", "Disponibilidad", "Actívate o desconéctate con un toque."),
    ("PAGO", "Liquidaciones", "Historial de pagos y cortes."),
    ("AYUDA", "Soporte", "Atención local por WhatsApp."),
]
for i, (icon, title, desc) in enumerate(features):
    col = i % 3
    row = i // 3
    cx = 0.62 + col * 4.08
    cy = 1.95 + row * 2.0
    add_card(slide, cx, cy, 3.88, 1.75)
    add_circle(slide, cx + 0.24, cy + 0.24, 0.5, LIGHT2)
    add_text(slide, cx + 0.24, cy + 0.38, 0.5, 0.2, icon, size=7, color=NAVY,
             bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, cx + 0.88, cy + 0.22, 2.8, 0.3, title, size=12, color=NAVY, bold=True)
    add_text(slide, cx + 0.88, cy + 0.62, 2.75, 0.95, desc, size=9.3, color=GRAY, spacing=1.05)
add_card(slide, 0.62, 6.0, 12.1, 0.7, fill=RGBColor(0xE8, 0xF5, 0xE9))
add_text(slide, 0.9, 6.15, 11.5, 0.4,
         "Tu teléfono es tu herramienta de trabajo. No necesitas una app adicional.",
         size=11, color=GREEN, bold=True)

# ---------------------------------------------------------------- 6 Reglas
slide = add_slide_base(
    prs, "Pedidos lejanos, reglas claras",
    kicker="Operación justa", number=6,
    subtitle="Los pedidos de 8 km o más se manejan distinto para cuidar tu tiempo y el trabajo del restaurante."
)
rules = [
    ("El restaurante espera", "En pedidos de 8 km o más, el restaurante no prepara hasta que un repartidor acepta."),
    ("Tú decides", "Antes de aceptar ves la distancia y la ganancia. Si no te conviene, no lo tomes."),
    ("30 minutos", "Si nadie acepta el pedido en 30 minutos, se cancela automáticamente."),
    ("Compromiso", "Si aceptas, entrega el pedido. El restaurante ya empezó a prepararlo por ti."),
]
for i, (title, desc) in enumerate(rules):
    col = i % 2
    row = i // 2
    cx = 0.62 + col * 6.15
    cy = 1.95 + row * 1.9
    add_card(slide, cx, cy, 5.95, 1.62)
    add_circle(slide, cx + 0.25, cy + 0.25, 0.42, ORANGE)
    add_text(slide, cx + 0.25, cy + 0.34, 0.42, 0.2, str(i + 1), size=11,
             color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, cx + 0.85, cy + 0.2, 4.8, 0.3, title, size=13, color=NAVY, bold=True)
    add_text(slide, cx + 0.85, cy + 0.6, 4.75, 0.8, desc, size=10, color=GRAY, spacing=1.08)
add_card(slide, 0.62, 5.85, 12.1, 0.7, fill=RGBColor(0xFF, 0xF2, 0xE8))
add_text(slide, 0.9, 6.0, 11.5, 0.4,
         "Así cuidamos tu tiempo, el trabajo del restaurante y la experiencia del cliente.",
         size=11.5, color=ORANGE_DARK, bold=True)

# ---------------------------------------------------------------- 7 Pagos
slide = add_slide_base(
    prs, "Pagos claros, sin letras chiquitas",
    kicker="Tus pagos", number=7,
    subtitle="Tu envío y tu propina se respetan. Todo queda registrado en la app."
)
add_card(slide, 0.62, 1.95, 6.0, 3.9)
add_text(slide, 0.9, 2.12, 5.4, 0.3, "Lo que recibes", size=13, color=NAVY, bold=True)
add_bullets(slide, 0.9, 2.62, 5.2, 3.0, [
    "100% del envío",
    "100% de la propina",
    "El km extra se suma a tu envío",
    "Efectivo o transferencia",
    "Historial de envíos, propinas y pagos",
    "Liquidaciones periódicas",
], size=11.5, spacing=10)
add_card(slide, 6.8, 1.95, 5.9, 3.9)
add_text(slide, 7.05, 2.12, 5.3, 0.3, "Ejemplo en efectivo", size=13, color=NAVY, bold=True)
add_text(slide, 7.05, 2.62, 5.2, 0.4, "Pedido de $230", size=20, color=ORANGE, bold=True)
add_text(slide, 7.05, 3.1, 5.2, 0.3, "Cliente paga: $230", size=11, color=NAVY)
add_text(slide, 7.05, 3.45, 5.2, 0.3, "Tu envío: $25 + propina", size=11, color=GREEN, bold=True)
add_text(slide, 7.05, 3.8, 5.2, 0.3, "El resto se registra para el restaurante y la plataforma.", size=9.5, color=GRAY)
add_line(slide, 7.05, 4.25, 12.3, 4.25, color=LIGHT2, width=0.7)
add_text(slide, 7.05, 4.4, 5.2, 0.8,
         "Si eliges transferencia, registra tu CLABE en tu perfil para recibir tus liquidaciones.",
         size=9.5, color=GRAY, spacing=1.1)
add_card(slide, 0.62, 6.1, 12.1, 0.6, fill=RGBColor(0xE8, 0xF5, 0xE9))
add_text(slide, 0.9, 6.24, 11.5, 0.3,
         "Lo que cobras y lo que te corresponde queda claro en tu historial.",
         size=10.5, color=GREEN, bold=True)

# ---------------------------------------------------------------- 8 Requisitos
slide = add_slide_base(
    prs, "Requisitos para unirte",
    kicker="Lo que necesitas", number=8,
    subtitle="Requisitos simples para empezar a repartir."
)
reqs = [
    ("Mayor de edad", "Con identificación oficial vigente."),
    ("Teléfono inteligente", "Con GPS, datos e internet."),
    ("Vehículo", "Bicicleta, motocicleta o automóvil."),
    ("Cuenta bancaria", "CLABE si prefieres pago por transferencia."),
    ("Actitud de servicio", "Trato amable con restaurantes y clientes."),
    ("Disponibilidad", "Tú decides cuándo conectarte."),
]
for i, (title, desc) in enumerate(reqs):
    col = i % 3
    row = i // 3
    cx = 0.62 + col * 4.08
    cy = 1.95 + row * 1.9
    add_card(slide, cx, cy, 3.88, 1.62)
    add_text(slide, cx + 0.25, cy + 0.17, 3.35, 0.3, title, size=12.5, color=NAVY, bold=True)
    add_text(slide, cx + 0.25, cy + 0.57, 3.35, 0.8, desc, size=9.8, color=GRAY, spacing=1.05)
add_card(slide, 0.62, 5.9, 12.1, 0.7, fill=RGBColor(0xFF, 0xF2, 0xE8))
add_text(slide, 0.9, 6.05, 11.5, 0.4,
         "No necesitas oficina ni invertir en una app. Tu vehículo y tu teléfono son suficientes.",
         size=11.5, color=ORANGE_DARK, bold=True)

# ---------------------------------------------------------------- 9 Empezar
slide = add_slide_base(
    prs, "Cómo empezar",
    kicker="Alta de repartidor", number=9,
    subtitle="En pocos pasos puedes estar conectado y recibiendo pedidos."
)
steps = [
    ("1", "Contáctanos", "Escríbenos por WhatsApp y te explicamos el proceso."),
    ("2", "Registro", "Documentos, vehículo y datos de pago."),
    ("3", "Activación", "Creamos tu perfil y te damos acceso a la app."),
    ("4", "Conéctate", "Activa tu disponibilidad y empieza a recibir pedidos."),
]
for i, (num, title, desc) in enumerate(steps):
    cx = 0.62 + i * 3.06
    add_card(slide, cx, 1.95, 2.88, 3.3)
    add_circle(slide, cx + 0.2, 2.15, 0.45, ORANGE)
    add_text(slide, cx + 0.2, 2.26, 0.45, 0.2, num, size=10, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, cx + 0.2, 2.78, 2.5, 0.3, title, size=13, color=NAVY, bold=True)
    add_text(slide, cx + 0.2, 3.25, 2.5, 1.3, desc, size=9.8, color=GRAY, spacing=1.1)
add_card(slide, 0.62, 5.65, 12.1, 0.95, fill=NAVY)
add_text(slide, 0.9, 5.8, 11.5, 0.3,
         "Te acompañamos en el alta y en tus primeros repartos.", size=15, color=WHITE, bold=True)
add_text(slide, 0.9, 6.2, 11.5, 0.3,
         "WhatsApp 412 134 0765  ·  old.lodoman@gmail.com",
         size=10, color=RGBColor(0xC9, 0xD2, 0xE3))

# ---------------------------------------------------------------- 10 FAQ
slide = add_slide_base(
    prs, "Preguntas frecuentes",
    kicker="Antes de empezar", number=10,
    subtitle="Lo que más nos preguntan los repartidores."
)
faqs = [
    ("¿Tengo horario fijo?", "No. Tú decides cuándo conectarte y cuándo terminar."),
    ("¿Cuánto cuesta unirme?", "No hay cuota de alta para repartidores."),
    ("¿Cómo recibo mis pagos?", "En efectivo o por transferencia, con historial en la app."),
    ("¿Puedo usar bicicleta, moto o auto?", "Sí, los tres vehículos son bienvenidos."),
    ("¿Qué pasa si no puedo entregar?", "No aceptes el pedido si no puedes cubrirlo; si surge algo, contacta a soporte."),
    ("¿Puedo trabajar en otra app?", "Tú decides tu disponibilidad y tus horarios."),
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

# ---------------------------------------------------------------- 11 CTA
slide = blank(prs)
add_rect(slide, 0, 0, 13.333, 7.5, NAVY_DARK)
add_rect(slide, 0, 0, 0.16, 7.5, ORANGE)
add_circle(slide, 10.7, -1.0, 3.3, RGBColor(0x24, 0x3B, 0x7A))
add_logo(slide, 0.85, 0.8, 5.0, on_dark=True)
add_text(slide, 0.85, 2.2, 11.4, 0.8,
         "Únete a TuPedidoJR.",
         size=36, color=WHITE, bold=True)
add_text(slide, 0.85, 3.05, 11.0, 0.7,
         "Reparte, gana y decide tu horario.\n100% del envío y 100% de la propina.",
         size=16, color=RGBColor(0xC9, 0xD2, 0xE3), spacing=1.15)
add_card(slide, 0.85, 4.25, 5.7, 1.45, fill=RGBColor(0x22, 0x35, 0x6E))
add_text(slide, 1.1, 4.42, 5.2, 0.3, "Da el primer paso", size=12, color=ORANGE, bold=True)
add_text(slide, 1.1, 4.78, 5.2, 0.7,
         "Escríbenos por WhatsApp y te ayudamos\ncon tu alta.",
         size=11, color=WHITE, spacing=1.1)
add_card(slide, 6.8, 4.25, 5.7, 1.45, fill=RGBColor(0x22, 0x35, 0x6E))
add_text(slide, 7.05, 4.42, 5.2, 0.3, "Contacto", size=12, color=ORANGE, bold=True)
add_text(slide, 7.05, 4.78, 5.2, 0.7,
         "WhatsApp 412 134 0765\nold.lodoman@gmail.com",
         size=11, color=WHITE, spacing=1.1)
add_text(slide, 0.85, 6.2, 11.0, 0.3,
         "Juventino Rosas, Guanajuato  ·  TuPedidoJR",
         size=10.5, color=RGBColor(0xC9, 0xD2, 0xE3))
add_text(slide, 0.85, 6.65, 11.0, 0.3, "Te esperamos.", size=18, color=ORANGE, bold=True)

path = OUT / "TuPedidoJR_Repartidores_2026.pptx"
prs.save(str(path))
print(path)
