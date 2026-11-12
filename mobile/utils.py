import flet as ft

APP_VERSION = "23"

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


def dialog_width(page: ft.Page, max_width: int = 340, min_width: int = 260) -> int:
    """Ancho seguro para el contenido de un diálogo en pantallas pequeñas."""
    try:
        width = float(page.width or 0)
    except (TypeError, ValueError):
        width = 0
    if width <= 0:
        width = 360
    return int(max(min_width, min(max_width, width - 72)))


def open_dlg(page: ft.Page, dlg: ft.AlertDialog):
    page.overlay.append(dlg)
    dlg.open = True
    page.update()


def close_dlg(page: ft.Page, dlg: ft.AlertDialog):
    dlg.open = False
    page.update()


async def launch_url(page: ft.Page, url: str) -> None:
    """Abre una URL con el lanzador del sistema (Flet 1.x)."""
    try:
        service = None
        for item in list(getattr(page, "services", []) or []):
            if isinstance(item, ft.UrlLauncher):
                service = item
                break
        if service is None:
            service = ft.UrlLauncher()
            page.services.append(service)
            page.update()
        await service.launch_url(url)
    except Exception:
        pass


async def report_error(page: ft.Page, message: str, detail: str) -> None:
    """Envía un error de la app al servidor para diagnóstico."""
    try:
        import httpx

        from mobile.api import api

        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{api.api_url}/api/v1/debug/client-log",
                json={
                    "message": message,
                    "detail": detail,
                    "version": APP_VERSION,
                    "route": getattr(page, "route", ""),
                },
            )
    except Exception:
        pass


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
