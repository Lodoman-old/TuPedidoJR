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
add_text(slide, 0.85, 0.75, 6.0, 0.35, "FONDO PERDIDO · CONVOCATORIA 2026", size=11,
         color=ORANGE, bold=True)
add_logo(slide, 0.85, 1.3, 5.25, on_dark=True)
add_text(slide, 0.85, 3.0, 11.0, 0.8,
         "Digitalización de restaurantes locales\ny empleo para repartidores.",
         size=30, color=WHITE, bold=True, spacing=0.98)
add_text(slide, 0.85, 4.05, 9.8, 0.6,
         "Proyecto en operación · Juventino Rosas y comunidades de Guanajuato",
         size=14, color=RGBColor(0xC9, 0xD2, 0xE3))
chips = [("$150,000", "apoyo solicitado"), ("100", "restaurantes meta"), ("30", "repartidores meta")]
x = 0.85
for value, label in chips:
    add_card(slide, x, 5.35, 3.5, 0.78, fill=RGBColor(0x22, 0x35, 0x6E), radius=0.1)
    add_text(slide, x + 0.2, 5.43, 3.1, 0.35, value, size=18, color=ORANGE, bold=True)
    add_text(slide, x + 0.2, 5.8, 3.0, 0.25, label, size=9, color=RGBColor(0xC9, 0xD2, 0xE3))
    x += 3.75
add_text(slide, 0.85, 6.55, 11.0, 0.3,
         "Monto propuesto, ajustable a las bases de la convocatoria.",
         size=8.5, color=RGBColor(0x9F, 0xAD, 0xC8), italic=True)
add_text(slide, 0.85, 6.88, 11.0, 0.28,
         "Solicitante: TuPedidoJR · Tecnología y comercio local",
         size=9, color=RGBColor(0x9F, 0xAD, 0xC8))

# ---------------------------------------------------------------- 2 Resumen
slide = add_slide_base(
    prs, "Una plataforma local que ya opera y puede escalar",
    kicker="Resumen del proyecto", number=2,
    subtitle="TuPedidoJR digitaliza restaurantes, coordina reparto local y genera ingresos para repartidores. Solicitamos apoyo para acelerar la adopción, no para construir el software desde cero."
)
kpis = [
    ("100", "restaurantes meta", "Afiliados y con menú digital al mes 12."),
    ("30", "repartidores activos", "Con capacitación e incentivos de arranque."),
    ("1,000", "pedidos mensuales", "Meta al mes 12 en la zona."),
    ("60", "personas capacitadas", "Restaurantes, cocina y reparto."),
]
for i, (value, label, note) in enumerate(kpis):
    cx = 0.62 + i * 3.06
    add_kpi(slide, cx, 2.0, 2.93, 1.95, value, label, note, value_size=28)
add_card(slide, 0.62, 4.35, 12.1, 1.55, fill=LIGHT2)
add_text(slide, 0.9, 4.52, 11.5, 0.34,
         "El software ya está desarrollado y en operación", size=15, color=NAVY, bold=True)
add_text(slide, 0.9, 4.92, 11.5, 0.8,
         "El apoyo se destina a adopción de restaurantes, materiales impresos, fotografía de menús, capacitación, promoción local y fortalecimiento de la red de repartidores.",
         size=11.5, color=GRAY, spacing=1.1)
add_card(slide, 0.62, 6.2, 12.1, 0.55, fill=RGBColor(0xFF, 0xF2, 0xE8))
add_text(slide, 0.9, 6.32, 11.5, 0.3,
         "Solicitud: $150,000 MXN · 12 meses · 100 restaurantes · 30 repartidores",
         size=10.5, color=ORANGE_DARK, bold=True)

# ---------------------------------------------------------------- 3 Problema
slide = add_slide_base(
    prs, "Restaurantes locales sin canal digital propio",
    kicker="Problemática", number=3,
    subtitle="En Juventino Rosas y comunidades cercanas, los negocios pequeños dependen de Uber Eats y DIDI o de canales informales para vender."
)
problems = [
    ("20–30%", "Comisión por pedido", "Uber Eats y DIDI cobran comisiones que reducen el margen de restaurantes pequeños."),
    ("Baja digitalización", "Menús y pedidos", "Muchos negocios no tienen menú en línea, pedidos digitales ni presencia propia."),
    ("Reparto informal", "Coordinación y ingresos", "Los repartidores operan sin una red estable, seguimiento ni pagos claros."),
]
for i, (value, label, note) in enumerate(problems):
    cx = 0.62 + i * 4.08
    add_card(slide, cx, 2.0, 3.92, 2.1)
    add_text(slide, cx + 0.28, 2.14, 3.35, 0.55, value, size=20 if i else 28,
             color=ORANGE, bold=True)
    add_text(slide, cx + 0.28, 2.82, 3.35, 0.35, label, size=11.5, color=NAVY, bold=True)
    add_text(slide, cx + 0.28, 3.2, 3.35, 0.75, note, size=9.5, color=GRAY, spacing=1.05)
add_card(slide, 0.62, 4.5, 12.1, 1.1, fill=RGBColor(0xFF, 0xF2, 0xE8), line=RGBColor(0xF7, 0xD3, 0xB5))
add_text(slide, 0.92, 4.68, 11.5, 0.34,
         "El dinero y los datos salen de la comunidad.", size=19, color=NAVY, bold=True)
add_text(slide, 0.92, 5.08, 11.5, 0.34,
         "Una plataforma local puede retener esa derrama y crear una red de reparto formal.",
         size=12, color=GRAY)
add_text(slide, 0.62, 6.65, 12.0, 0.25,
         "Comisiones de Uber Eats y DIDI: referencia de mercado. Verificar términos vigentes.",
         size=8, color=GRAY_LIGHT, italic=True)

# ---------------------------------------------------------------- 4 Solución
slide = add_slide_base(
    prs, "Tecnología local, operación local, beneficio local",
    kicker="Solución", number=4,
    subtitle="Una alternativa para que los restaurantes vendan directo, con costo fijo y sin comisión por platillo."
)
solutions = [
    ("Menú digital + QR", "Cada restaurante tiene su página, fotos, precios y un QR para mesa, mostrador y volantes."),
    ("Pedidos y pagos", "El cliente pide desde la app o web; paga en efectivo o por transferencia."),
    ("Reparto respaldado", "La plataforma coordina repartidores, seguimiento GPS y respaldo de entrega."),
    ("Ingreso para repartidores", "Reciben el 100% del envío y el 100% de la propina; el km extra se suma a su pago."),
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
    add_text(slide, cx + 0.85, cy + 0.66, 4.75, 0.78, desc, size=10.2, color=GRAY, spacing=1.08)
add_text(slide, 0.62, 6.3, 12.0, 0.4,
         "La tecnología ya está construida; el apoyo permite llevarla a más restaurantes y comunidades.",
         size=13, color=ORANGE_DARK, bold=True)

# ---------------------------------------------------------------- 5 Producto
slide = add_slide_base(
    prs, "El proyecto ya está en operación",
    kicker="Producto y tracción", number=5,
    subtitle="No es una idea: la plataforma, la app y la operación ya existen y están listas para escalar."
)
features = [
    ("APP", "App Android + web", "Cliente, restaurante y repartidor en una sola plataforma."),
    ("QR", "Menú digital", "Página propia, fotos, categorías, opciones y horarios."),
    ("$", "Pagos y cobros", "Efectivo y transferencia; conciliación y comprobantes."),
    ("GPS", "Reparto y seguimiento", "Asignación, ubicación en vivo y ETA por ruta."),
    ("PUSH", "Notificaciones", "Avisos de pedido, estado y recordatorios."),
    ("ML", "Ganancias y liquidaciones", "Cuentas claras para restaurante, repartidor y administración."),
]
for i, (icon, title, desc) in enumerate(features):
    col = i % 3
    row = i // 3
    cx = 0.62 + col * 4.08
    cy = 1.95 + row * 2.0
    add_card(slide, cx, cy, 3.88, 1.75)
    add_circle(slide, cx + 0.24, cy + 0.24, 0.5, LIGHT2)
    add_text(slide, cx + 0.24, cy + 0.38, 0.5, 0.2, icon, size=7.5, color=NAVY,
             bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, cx + 0.88, cy + 0.22, 2.8, 0.3, title, size=12.5, color=NAVY, bold=True)
    add_text(slide, cx + 0.88, cy + 0.62, 2.75, 0.95, desc, size=9.5, color=GRAY, spacing=1.05)
add_card(slide, 0.62, 6.0, 12.1, 0.7, fill=RGBColor(0xE8, 0xF5, 0xE9))
add_text(slide, 0.9, 6.15, 11.5, 0.4,
         "Estado actual: plataforma en producción, piloto operativo y app Android disponible.",
         size=11, color=GREEN, bold=True)

# ---------------------------------------------------------------- 6 Beneficiarios
slide = add_slide_base(
    prs, "A quién beneficia el proyecto",
    kicker="Beneficiarios", number=6,
    subtitle="El impacto se concentra en restaurantes, repartidores, clientes y la economía local."
)
beneficiaries = [
    ("Restaurantes", "Más margen, menú digital, materiales, fotografía y capacitación."),
    ("Repartidores", "Ingreso por envío, 100% de la propina, horarios flexibles y una red formal."),
    ("Clientes", "Opción local, precios claros, seguimiento y reembolso cuando aplica."),
    ("Comunidad", "El dinero se queda en la zona, se digitalizan MIPYMES y se crea empleo."),
]
for i, (title, desc) in enumerate(beneficiaries):
    col = i % 2
    row = i // 2
    cx = 0.62 + col * 6.15
    cy = 1.95 + row * 1.9
    add_card(slide, cx, cy, 5.95, 1.62)
    add_text(slide, cx + 0.28, cy + 0.2, 5.4, 0.3, title, size=14, color=NAVY, bold=True)
    add_text(slide, cx + 0.28, cy + 0.62, 5.35, 0.8, desc, size=10.5, color=GRAY, spacing=1.08)
add_card(slide, 0.62, 5.85, 12.1, 0.7, fill=RGBColor(0xFF, 0xF2, 0xE8))
add_text(slide, 0.9, 6.0, 11.5, 0.4,
         "Meta: 100 restaurantes, 30 repartidores activos y 60 personas capacitadas.",
         size=11.5, color=ORANGE_DARK, bold=True)

# ---------------------------------------------------------------- 7 Indicadores
slide = add_slide_base(
    prs, "Indicadores de impacto y seguimiento",
    kicker="Resultados medibles", number=7,
    subtitle="El proyecto se compromete a reportar resultados con evidencia verificable."
)
headers = ["Indicador", "Meta a 12 meses", "Cómo se mide"]
rows = [
    ["Restaurantes afiliados", "100", "Altas y afiliaciones vigentes en la plataforma"],
    ["Menús digitales y QR entregados", "100", "Registro de entrega y materiales"],
    ["Repartidores activos", "30", "Repartidores con al menos un reparto al mes"],
    ["Pedidos mensuales", "1,000", "Reporte de la plataforma"],
    ["Personas capacitadas", "60", "Listas de asistencia y capacitación"],
    ["Ahorro por comisiones", "$45 por pedido de $200", "Comparativo vs. 25% de comisión"],
    ["Pagos y liquidaciones registradas", "100%", "Reporte financiero y comprobantes"],
]
add_table(slide, 0.62, 1.95, 12.1, 4.6, headers, rows,
          col_widths=[3.7, 3.2, 5.2], font_size=9.8, row_height=0.58,
          center_columns=False)
add_text(slide, 0.62, 6.65, 12.0, 0.25,
         "Reportes mensuales, comprobantes y auditoría de los recursos del apoyo.",
         size=9, color=GRAY, italic=True)

# ---------------------------------------------------------------- 8 Uso de fondos
slide = add_slide_base(
    prs, "Uso del apoyo: $150,000 MXN",
    kicker="Presupuesto", number=8,
    subtitle="El software ya está desarrollado. El apoyo se concentra en adopción, materiales y operación."
)
headers = ["Concepto", "Monto", "%"]
rows = [
    ["Operación tecnológica anual (VPS, desarrollo, administración)", "$30,000", "20%"],
    ["Fotografía, menús y materiales para 100 restaurantes", "$50,000", "33%"],
    ["Lanzamiento y promoción local", "$30,000", "20%"],
    ["Red de repartidores (capacitación, kits e incentivos)", "$20,000", "13%"],
    ["Capacitación y acompañamiento a restaurantes", "$10,000", "7%"],
    ["Contingencia y administración", "$10,000", "7%"],
    ["Total", "$150,000", "100%"],
]
add_table(slide, 0.62, 1.95, 8.5, 4.6, headers, rows,
          col_widths=[5.5, 1.6, 0.9], font_size=9.8, row_height=0.58,
          center_columns=True)
add_card(slide, 9.35, 1.95, 3.35, 4.6, fill=LIGHT2)
add_text(slide, 9.6, 2.12, 2.9, 0.3, "Contraparte del proyecto", size=11.5, color=NAVY, bold=True)
add_text(slide, 9.6, 2.55, 2.85, 3.6,
         "La plataforma ya está desarrollada y operando.\n\nEl apoyo no financia construir el software desde cero: acelera la adopción, la producción de materiales y la red de repartidores.\n\nMontos propuestos, ajustables a las bases de la convocatoria.",
         size=9.3, color=GRAY, spacing=1.1)
add_text(slide, 0.62, 6.75, 12.0, 0.25,
         "Se entregarán comprobantes y reportes de cada partida.",
         size=8.5, color=GRAY_LIGHT, italic=True)

# ---------------------------------------------------------------- 9 Sostenibilidad
slide = add_slide_base(
    prs, "Sostenibilidad después del apoyo",
    kicker="Modelo financiero", number=9,
    subtitle="El apoyo financia el arranque. La operación se sostiene con ingresos propios."
)
add_card(slide, 0.62, 1.95, 5.9, 3.7)
add_text(slide, 0.9, 2.12, 5.3, 0.3, "Fuentes de ingreso", size=13, color=NAVY, bold=True)
add_bullets(slide, 0.9, 2.6, 5.2, 2.8, [
    "$500 al año por restaurante afiliado",
    "$5 por pedido del restaurante",
    "$5 de cuota de servicio del cliente",
    "El envío va al repartidor, no es margen de la plataforma",
], size=11, spacing=8)
add_card(slide, 6.7, 1.95, 6.0, 3.7)
add_text(slide, 6.95, 2.12, 5.4, 0.3, "Punto de equilibrio", size=13, color=NAVY, bold=True)
add_text(slide, 6.95, 2.6, 5.4, 0.45, "60 restaurantes", size=24, color=ORANGE, bold=True)
add_text(slide, 6.95, 3.1, 5.4, 0.3, "cubren $30,000 al año con la afiliación", size=10, color=GRAY)
add_text(slide, 6.95, 3.55, 5.4, 0.45, "250 pedidos/mes", size=24, color=ORANGE, bold=True)
add_text(slide, 6.95, 4.05, 5.4, 0.3, "cubren $30,000 al año con la cuota por pedido", size=10, color=GRAY)
add_text(slide, 6.95, 4.5, 5.4, 0.8,
         "El modelo no depende permanentemente del subsidio.", size=11, color=GREEN, bold=True)
add_card(slide, 0.62, 5.9, 12.1, 0.8, fill=RGBColor(0xFF, 0xF2, 0xE8))
add_text(slide, 0.9, 6.05, 11.5, 0.45,
         "Proyección: 100 restaurantes y 1,000 pedidos/mes al mes 12; expansión a nuevos municipios después.",
         size=10.5, color=ORANGE_DARK, bold=True)

# ---------------------------------------------------------------- 10 Timeline
slide = add_slide_base(
    prs, "Ruta de implementación en 12 meses",
    kicker="Cronograma", number=10,
    subtitle="Hitos medibles, con reporte de avance y comprobantes."
)
phases = [
    ("TRIMESTRE 1", "30 restaurantes", "Alta, fotografía de menús, materiales y capacitación inicial."),
    ("TRIMESTRE 2", "60 restaurantes", "Red de repartidores, promoción local y primeras métricas."),
    ("TRIMESTRE 3", "80 restaurantes", "Optimización de operación y acompañamiento a restaurantes."),
    ("TRIMESTRE 4", "100 restaurantes", "1,000 pedidos/mes y reporte final de impacto."),
]
for i, (phase, target, desc) in enumerate(phases):
    cx = 0.62 + i * 3.06
    add_card(slide, cx, 1.95, 2.88, 3.3)
    add_text(slide, cx + 0.2, 2.15, 2.5, 0.3, phase, size=9.5, color=ORANGE, bold=True)
    add_text(slide, cx + 0.2, 2.52, 2.5, 0.55, target, size=18, color=NAVY, bold=True)
    add_text(slide, cx + 0.2, 3.22, 2.5, 1.3, desc, size=9.2, color=GRAY, spacing=1.1)
    add_circle(slide, cx + 2.25, 4.65, 0.35, ORANGE)
    add_text(slide, cx + 2.25, 4.72, 0.35, 0.18, str(i + 1), size=9, color=WHITE,
             bold=True, align=PP_ALIGN.CENTER)
add_card(slide, 0.62, 5.65, 12.1, 1.0, fill=NAVY)
add_text(slide, 0.9, 5.8, 11.5, 0.3,
         "Meta: 100 restaurantes, 30 repartidores y 60 personas capacitadas.", size=15, color=WHITE, bold=True)
add_text(slide, 0.9, 6.2, 11.5, 0.3,
         "Cada trimestre se entrega reporte de avance, evidencia y comprobantes.",
         size=10, color=RGBColor(0xC9, 0xD2, 0xE3))

# ---------------------------------------------------------------- 11 Equipo
slide = add_slide_base(
    prs, "Equipo, gobernanza y transparencia",
    kicker="Ejecución", number=11,
    subtitle="Un equipo local con la plataforma ya construida y controles claros sobre el uso de los recursos."
)
roles = [
    ("Dirección general", "Estrategia, alianzas con restaurantes y relación con la convocatoria."),
    ("Tecnología", "Plataforma, seguridad, disponibilidad y soporte técnico."),
    ("Operación", "Alta de restaurantes, materiales, capacitación y red de repartidores."),
    ("Administración", "Presupuesto, comprobantes, reportes y cumplimiento."),
]
for i, (title, desc) in enumerate(roles):
    col = i % 2
    row = i // 2
    cx = 0.62 + col * 6.15
    cy = 1.95 + row * 1.65
    add_card(slide, cx, cy, 5.95, 1.4)
    add_text(slide, cx + 0.25, cy + 0.18, 5.4, 0.3, title, size=12.5, color=NAVY, bold=True)
    add_text(slide, cx + 0.25, cy + 0.58, 5.35, 0.7, desc, size=9.8, color=GRAY, spacing=1.05)
add_card(slide, 0.62, 5.45, 12.1, 1.1, fill=LIGHT2)
add_text(slide, 0.9, 5.6, 11.5, 0.3,
         "Controles: reportes mensuales, comprobantes, indicadores y auditoría.", size=11.5, color=NAVY, bold=True)
add_text(slide, 0.9, 5.98, 11.5, 0.4,
         "Estatus: proyecto en operación, en proceso de formalización según las bases de la convocatoria.",
         size=9.5, color=GRAY)

# ---------------------------------------------------------------- 12 Riesgos
slide = add_slide_base(
    prs, "Riesgos y mitigación",
    kicker="Control del proyecto", number=12,
    subtitle="Los principales riesgos están identificados y tienen una respuesta operativa."
)
headers = ["Riesgo", "Mitigación"]
rows = [
    ["Adopción lenta de restaurantes", "Cuota baja, materiales y fotografía incluidos; acompañamiento y piloto demostrable."],
    ["Oferta insuficiente de repartidores", "100% del envío + propina, incentivos de arranque y horarios flexibles."],
    ["Competencia de Uber Eats y DIDI", "Costo fijo, trato local, menú propio y respaldo de entrega."],
    ["Ejecución del presupuesto", "Reportes mensuales, comprobantes y partidas definidas."],
    ["Sostenibilidad después del apoyo", "Ingresos por afiliación y pedido; equilibrio a los 60 restaurantes."],
]
add_table(slide, 0.62, 1.95, 12.1, 4.0, headers, rows,
          col_widths=[4.2, 7.9], font_size=10, row_height=0.65,
          center_columns=False)
add_card(slide, 0.62, 6.15, 12.1, 0.55, fill=RGBColor(0xE8, 0xF5, 0xE9))
add_text(slide, 0.9, 6.28, 11.5, 0.3,
         "La plataforma ya opera: el riesgo tecnológico está reducido; el foco es adopción y ejecución.",
         size=10.5, color=GREEN, bold=True)

# ---------------------------------------------------------------- 13 Alineación
slide = add_slide_base(
    prs, "Alineación con el apoyo gubernamental",
    kicker="Impacto público", number=13,
    subtitle="Un proyecto que combina digitalización de MIPYMES, empleo local y derrama económica."
)
alignment = [
    ("Digitalización de MIPYMES", "Menús, pedidos y cobros digitales para restaurantes pequeños."),
    ("Empleo y autoempleo", "Red formal de repartidores con ingresos claros y flexibles."),
    ("Derrama económica local", "El gasto de los clientes se queda en la comunidad."),
    ("Inclusión financiera", "Pagos, cuentas claras y comprobantes para negocios y repartidores."),
    ("Innovación desde el municipio", "Tecnología desarrollada y operada localmente."),
]
for i, (title, desc) in enumerate(alignment):
    cx = 0.62 + i * 2.47
    add_card(slide, cx, 1.95, 2.27, 3.25)
    add_circle(slide, cx + 0.2, 2.15, 0.42, ORANGE)
    add_text(slide, cx + 0.2, 2.26, 0.42, 0.2, str(i + 1), size=9, color=WHITE,
             bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, cx + 0.2, 2.78, 1.9, 0.7, title, size=10.5, color=NAVY, bold=True, spacing=1.0)
    add_text(slide, cx + 0.2, 3.55, 1.9, 1.25, desc, size=9, color=GRAY, spacing=1.05)
add_card(slide, 0.62, 5.65, 12.1, 0.9, fill=RGBColor(0xFF, 0xF2, 0xE8))
add_text(slide, 0.9, 5.8, 11.5, 0.5,
         "Cada peso del apoyo se traduce en restaurantes digitalizados, empleo local y dinero que se queda en la comunidad.",
         size=11.5, color=ORANGE_DARK, bold=True, spacing=1.05)

# ---------------------------------------------------------------- 14 Cierre
slide = blank(prs)
add_rect(slide, 0, 0, 13.333, 7.5, NAVY_DARK)
add_rect(slide, 0, 0, 0.16, 7.5, ORANGE)
add_circle(slide, 10.7, -1.0, 3.3, RGBColor(0x24, 0x3B, 0x7A))
add_logo(slide, 0.85, 0.8, 5.0, on_dark=True)
add_text(slide, 0.85, 2.2, 11.4, 0.8,
         "Tecnología local que genera empleo y margen.",
         size=32, color=WHITE, bold=True)
add_text(slide, 0.85, 3.15, 11.0, 0.7,
         "Solicitud: $150,000 MXN para 100 restaurantes, 30 repartidores y 60 personas capacitadas.",
         size=15, color=RGBColor(0xC9, 0xD2, 0xE3), spacing=1.1)
add_card(slide, 0.85, 4.25, 5.7, 1.45, fill=RGBColor(0x22, 0x35, 0x6E))
add_text(slide, 1.1, 4.42, 5.2, 0.3, "Solicitante", size=12, color=ORANGE, bold=True)
add_text(slide, 1.1, 4.78, 5.2, 0.7,
         "TuPedidoJR\nJuventino Rosas, Guanajuato",
         size=11, color=WHITE, spacing=1.1)
add_card(slide, 6.8, 4.25, 5.7, 1.45, fill=RGBColor(0x22, 0x35, 0x6E))
add_text(slide, 7.05, 4.42, 5.2, 0.3, "Contacto", size=12, color=ORANGE, bold=True)
add_text(slide, 7.05, 4.78, 5.2, 0.7,
         "WhatsApp 412 134 0765\nold.lodoman@gmail.com",
         size=11, color=WHITE, spacing=1.1)
add_text(slide, 0.85, 6.2, 11.0, 0.3,
         "Proyecto en operación · Apoyo para acelerar adopción, materiales y red de repartidores.",
         size=10, color=RGBColor(0xC9, 0xD2, 0xE3))
add_text(slide, 0.85, 6.65, 11.0, 0.3, "Gracias.", size=18, color=ORANGE, bold=True)

path = OUT / "TuPedidoJR_FondoPerdido_2026.pptx"
prs.save(str(path))
print(path)
