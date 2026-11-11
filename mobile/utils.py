import flet as ft

STATUS_LABELS = {
    "pending": "Pendiente",
    "confirmed": "Confirmado",
    "preparing": "Preparando",
    "ready": "Listo",
    "in_delivery": "En reparto",
    "picked_up": "Recogido",
    "delivered": "Entregado",
    "cancelled": "Cancelado",
    "accepted": "Aceptado",
    "buying": "Comprando",
    "purchased": "Comprado",
    "completed": "Completado",
    "paid": "Pagado",
    "approved": "Aprobado",
    "in_process": "En proceso",
    "rejected": "Rechazado",
    "refunded": "Reembolsado",
    "active": "Activo",
    "inactive": "Inactivo",
}

PAYOUT_STATUS_LABELS = {
    "pending": "Pendiente",
    "paid": "Pagada",
    "confirmed": "Confirmada",
    "cancelled": "Cancelada",
}

PAYMENT_STATUS_LABELS = {
    "pending": "Pendiente",
    "approved": "Aprobado",
    "in_process": "En proceso",
    "rejected": "Rechazado",
    "refunded": "Reembolsado",
    "cancelled": "Cancelado",
}


def open_dlg(page: ft.Page, dlg: ft.AlertDialog):
    page.overlay.append(dlg)
    dlg.open = True
    page.update()


def close_dlg(page: ft.Page, dlg: ft.AlertDialog):
    dlg.open = False
    page.update()


def snack(page: ft.Page, text: str, bgcolor=ft.Colors.GREEN):
    s = ft.SnackBar(ft.Text(text), bgcolor=bgcolor)
    page.overlay.append(s)
    s.open = True
    page.update()


def pick_image_file() -> str | None:
    """Open a native file dialog to pick an image. Returns path or None."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="Seleccionar imagen",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.webp"), ("Todos", "*.*")],
        )
        root.destroy()
        return path if path else None
    except Exception:
        return None
