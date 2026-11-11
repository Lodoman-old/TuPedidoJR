import flet as ft
from mobile.api import api, ApiError
from mobile.utils import snack


PAYOUT_STATUS = {
    "pending": ("Pendiente", ft.Colors.AMBER),
    "paid": ("Pagada", ft.Colors.GREEN),
    "confirmed": ("Confirmada", ft.Colors.GREEN),
    "cancelled": ("Cancelada", ft.Colors.RED),
}


def restaurant_earnings_view(page: ft.Page, rid: str):
    loading = ft.ProgressBar(visible=False)
    error_text = ft.Text("", color=ft.Colors.RED)
    scroll = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, spacing=8)

    async def load():
        loading.visible = True
        page.update()
        try:
            r = await api.get_restaurant(rid)
            data = await api.get_restaurant_earnings(rid)
            payouts = await api.list_restaurant_payouts(rid)
            scroll.controls.clear()
            fmt = lambda n: f"${float(n or 0):.2f}"

            available = float(data.get("available_for_payout", 0))
            pending = float(data.get("total_pending_payouts", 0))

            cards = [
                ft.Row([
                    ft.Container(ft.Column([ft.Text("Ganancia neta", size=12, color=ft.Colors.GREY), ft.Text(fmt(data["net_earned"]), size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN)], spacing=2), padding=12, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH, border_radius=10, expand=True),
                    ft.Container(ft.Column([ft.Text("Pedidos", size=12, color=ft.Colors.GREY), ft.Text(str(data["total_orders"]), size=18, weight=ft.FontWeight.BOLD)], spacing=2), padding=12, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH, border_radius=10, expand=True),
                ], spacing=8),
                ft.Row([
                    ft.Container(ft.Column([ft.Text("Disponible", size=12, color=ft.Colors.GREY), ft.Text(fmt(available), size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN)], spacing=2), padding=12, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH, border_radius=10, expand=True),
                    ft.Container(ft.Column([ft.Text("En proceso", size=12, color=ft.Colors.GREY), ft.Text(fmt(pending), size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER)], spacing=2), padding=12, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH, border_radius=10, expand=True),
                ], spacing=8),
            ]

            if pending > 0:
                cards.append(ft.Text(f"Liquidación en proceso: {fmt(pending)}", size=12, color=ft.Colors.AMBER, weight=ft.FontWeight.BOLD))

            if available > 0:
                cards.append(ft.ElevatedButton(
                    f"Solicitar liquidación — {fmt(available)}",
                    color=ft.Colors.WHITE,
                    bgcolor=ft.Colors.GREEN,
                    on_click=lambda e: page.run_task(request_payout),
                    expand=True,
                ))

            cards.extend([
                ft.Divider(height=1),
                ft.Text("Detalle", size=14, weight=ft.FontWeight.BOLD),
                _detail_row("Subtotal", fmt(data["total_subtotal"])),
                _detail_row("Comisión", f"-{fmt(data['total_commission'])}", ft.Colors.RED),
                _detail_row("Cuota fija (cliente)", fmt(data["total_flat_fees"]), ft.Colors.GREY),
                _detail_row("Gastos envío", fmt(data["total_delivery_fees"])),
                ft.Divider(height=1),
                _detail_row("Tipo de cobro", "", ft.Colors.GREY),
                _detail_row("Efectivo (cobra repartidor)", fmt(data["total_collected_cash"])),
                _detail_row("Transferencia / MP", fmt(data["total_collected_transfer"])),
                _detail_row("Por cobrar a plataforma", fmt(data["pending_from_platform"]), ft.Colors.BLUE),
                ft.Divider(height=1),
                ft.Text("Historial de liquidaciones", size=14, weight=ft.FontWeight.BOLD),
            ])

            if payouts:
                for p in payouts:
                    label, color = PAYOUT_STATUS.get(p.get("status"), (p.get("status", ""), ft.Colors.GREY))
                    cards.append(ft.Container(
                        content=ft.Row([
                            ft.Column([
                                ft.Text(f"{p['period_start']} a {p['period_end']}", size=12, weight=ft.FontWeight.BOLD),
                                ft.Text(f"{p['orders_count']} pedidos", size=10, color=ft.Colors.GREY),
                            ], spacing=2, expand=True),
                            ft.Column([
                                ft.Text(fmt(p["net_payout"]), size=13),
                                ft.Text(label, size=10, color=color),
                            ], horizontal_alignment=ft.CrossAxisAlignment.END, spacing=2),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        padding=10,
                        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
                        border_radius=8,
                    ))
            else:
                cards.append(ft.Text("Sin liquidaciones todavía", size=12, color=ft.Colors.GREY))

            cards.extend([
                ft.Divider(height=1),
                ft.Text("Datos bancarios", size=14, weight=ft.FontWeight.BOLD),
                ft.Text(f"Banco: {r.get('bank_name', '-')}", size=13, color=ft.Colors.GREY),
                ft.Text(f"Titular: {r.get('bank_account_holder', '-')}", size=13, color=ft.Colors.GREY),
                ft.Text(f"CLABE: {r.get('bank_clabe', '-')}", size=13, color=ft.Colors.GREY),
            ])

            scroll.controls.extend(cards)
        except ApiError as ex:
            error_text.value = ex.detail
        finally:
            loading.visible = False
            page.update()

    async def request_payout():
        try:
            payout = await api.request_restaurant_payout(rid)
            snack(page, f"Liquidación solicitada: ${float(payout['net_payout']):.2f}")
            await load()
        except ApiError as ex:
            snack(page, f"Error: {ex.detail}", ft.Colors.RED)

    page.run_task(load)

    appbar = ft.AppBar(
        leading=ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda e: page.run_task(page.push_route, f"/restaurant/{rid}")),
        title=ft.Text("Ganancias"),
    )

    return ft.View(
        route=f"/restaurant-earnings/{rid}",
        controls=[appbar, ft.Column([error_text, loading, scroll], expand=True, spacing=4)],
    )


def _detail_row(label: str, value: str, color=None):
    return ft.Row([
        ft.Text(label, size=13, expand=True, color=ft.Colors.GREY),
        ft.Text(value, size=13, weight=ft.FontWeight.BOLD, color=color or ft.Colors.ON_SURFACE),
    ], spacing=8)
