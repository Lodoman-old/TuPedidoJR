"""Actualiza las presentaciones con la política de certeza y el corte."""
from pathlib import Path

from pptx import Presentation


def replace_in_paragraph(paragraph, old, new):
    if old not in paragraph.text:
        return False
    full = paragraph.text.replace(old, new)
    runs = paragraph.runs
    if runs:
        for run in runs[1:]:
            run.text = ""
        runs[0].text = full
    else:
        paragraph.text = full
    return True


def replace_in_shape(shape, old, new):
    changed = False
    if getattr(shape, "has_text_frame", False):
        for paragraph in shape.text_frame.paragraphs:
            if replace_in_paragraph(paragraph, old, new):
                changed = True
    if getattr(shape, "has_table", False):
        for row in shape.table.rows:
            for cell in row.cells:
                for paragraph in cell.text_frame.paragraphs:
                    if replace_in_paragraph(paragraph, old, new):
                        changed = True
    if getattr(shape, "shapes", None):
        for child in shape.shapes:
            if replace_in_shape(child, old, new):
                changed = True
    return changed


def apply(path, replacements):
    prs = Presentation(path)
    count = 0
    for slide in prs.slides:
        for shape in slide.shapes:
            for old, new in replacements:
                if replace_in_shape(shape, old, new):
                    count += 1
    prs.save(path)
    print("OK", path.name, "cambios:", count)


def main():
    base = Path(".")
    apply(base / "TuPedidoJR_Repartidores_2026.pptx", [
        ("Sin comisión sobre tu envío", "Sin comisión ni tarifa de retorno"),
        (
            "El envío y la propina son tuyos. TuPedidoJR no se queda con un porcentaje de tu entrega.",
            "El envío y la propina son tuyos. Si no puedes entregar y no es tu culpa, también se te paga completo.",
        ),
        ("Liquidaciones periódicas", "Corte con saldo neto en la app"),
        (
            "Si un cliente no abre, no recibe o no paga, TuPedidoJR te respalda: te paga tu envío y también cubre al restaurante.",
            "Si un cliente no abre, no recibe o no paga, TuPedidoJR te respalda: te paga tu envío y cubre al restaurante. Puedes llevar hasta 5 servicios activos.",
        ),
        (
            "No aceptes el pedido si no puedes cubrirlo; si surge algo, contacta a soporte.",
            "Reporta con foto y motivo. Si no es tu culpa, cobras tu viaje completo. Si es tu culpa, pierdes el envío. La plataforma cubre al negocio hasta $500.",
        ),
    ])
    apply(base / "TuPedidoJR_Restaurantes_2026.pptx", [
        (
            "Con TuPedidoJR: $195 por pedido, 0% comisión por platillo y respaldo de pago.",
            "Con TuPedidoJR: $195 por pedido, 0% comisión por platillo y respaldo si no se entrega.",
        ),
        (
            "El reparto informal parece barato, pero si el cliente no paga o no recibe, el restaurante pierde. TuPedidoJR responde y da seguimiento.",
            "El reparto informal parece barato, pero si el cliente no paga o no recibe, el restaurante pierde. TuPedidoJR responde y da seguimiento; si el producto se pierde o se desecha, te lo paga.",
        ),
        (
            "El cliente. El repartidor recibe el 100% del envío.",
            "El cliente. El repartidor recibe el 100% del envío; si no se entrega, se le paga completo salvo culpa comprobada.",
        ),
    ])
    apply(base / "TuPedidoJR_2026.pptx", [
        (
            "Opción local, precios claros, seguimiento y reembolso cuando aplica.",
            "Opción local, precios claros, seguimiento y respuesta de la plataforma cuando algo falla.",
        ),
        (
            "Cubrimos el pago al restaurante/negocio y al repartidor si el cliente no paga.",
            "Cubrimos al restaurante/negocio y al repartidor cuando el producto se pierde o se desecha. Si se recupera, no se paga el producto.",
        ),
    ])
    apply(base / "TuPedidoJR_Propuesta_2026.pptx", [
        (
            "Recibe aviso, seguimiento y reembolso cuando aplica.",
            "Recibe aviso, seguimiento y respuesta de la plataforma.",
        ),
        (
            "100% del envío y 100% de la propina. Km extra incluido.",
            "100% del envío y 100% de la propina. Km extra incluido. Si no se entrega, se paga completo salvo culpa comprobada.",
        ),
    ])


if __name__ == "__main__":
    main()
