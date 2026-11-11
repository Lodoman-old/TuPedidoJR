import asyncio
import flet as ft
from mobile.api import api, ApiError
from mobile.utils import PAYMENT_STATUS_LABELS


PAYMENT_COLORS = {
    "pending": ft.Colors.ORANGE,
    "approved": ft.Colors.GREEN,
    "in_process": ft.Colors.BLUE,
    "rejected": ft.Colors.RED,
    "refunded": ft.Colors.GREY,
    "cancelled": ft.Colors.RED,
}


def payment_view(page: ft.Page, order_id: str):
    status_label = ft.Text("Pendiente", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE)
    status_msg = ft.Text("", size=14)
    pay_btn = ft.FilledButton("Pagar con Mercado Pago", width=300, disabled=False)
    back_btn = ft.OutlinedButton("Ver mis pedidos", on_click=lambda _: page.run_task(page.push_route, "/orders"))
    polling = False

    async def check_status():
        nonlocal polling
        while polling:
            await asyncio.sleep(3)
            try:
                data = await api.payment_status(order_id)
                st = data["payment_status"]
                status_label.value = PAYMENT_STATUS_LABELS.get(st, st).upper()
                status_label.color = PAYMENT_COLORS.get(st, ft.Colors.GREY)
                if st == "approved":
                    status_msg.value = "¡Pago confirmado!"
                    pay_btn.disabled = True
                    polling = False
                    page.update()
                    await asyncio.sleep(1)
                    await page.push_route("/orders")
                    return
                elif st in ("rejected", "cancelled"):
                    status_msg.value = "El pago no se completó. Intenta de nuevo."
                    pay_btn.disabled = False
                    polling = False
                page.update()
            except ApiError:
                pass

    async def pay(e):
        pay_btn.disabled = True
        page.update()
        try:
            pref = await api.create_preference(order_id)
            url = pref.get("checkout_url") or pref["sandbox_init_point"]
            page.launch_url(url)
            nonlocal polling
            polling = True
            asyncio.create_task(check_status())
        except ApiError as ex:
            status_msg.value = f"Error: {ex.detail}"
            pay_btn.disabled = False
            page.update()

    pay_btn.on_click = lambda e: page.run_task(pay, e)

    appbar = ft.AppBar(title=ft.Text(f"Pago - #{order_id[:8]}"))

    return ft.View(
        route=f"/payment/{order_id}",
        controls=[
            appbar,
            ft.SafeArea(ft.Column([
                ft.Container(height=40),
                ft.Icon(ft.Icons.PAYMENT, size=64, color=ft.Colors.BLUE),
                ft.Container(height=20),
                status_label,
                status_msg,
                ft.Container(height=30),
                pay_btn,
                ft.Container(height=10),
                back_btn,
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, scroll=ft.ScrollMode.AUTO))
        ]
    )
