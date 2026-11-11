import asyncio
from datetime import datetime

import flet as ft
from mobile.api import api, ApiError
from mobile.utils import STATUS_LABELS


def orders_view(page: ft.Page):
    loading = ft.ProgressBar(visible=False)
    error_text = ft.Text("", color=ft.Colors.RED)
    updated_text = ft.Text("Se actualiza cada 15 s", size=11, color=ft.Colors.GREY)
    list_view = ft.ListView(spacing=8, padding=10, expand=True)
    state = {"sig": None}

    async def load(silent: bool = False):
        if not silent:
            loading.visible = True
        error_text.value = ""
        page.update()
        try:
            data = await api.list_orders()
            ordered = sorted(data, key=lambda x: x["placed_at"], reverse=True)
            signature = tuple(
                (o["id"], o["status"], o.get("delivery_person_id")) for o in ordered
            )
            if not silent or signature != state["sig"]:
                list_view.controls.clear()
                for o in ordered:
                    list_view.controls.append(_order_card(page, o))
                if not ordered:
                    list_view.controls.append(
                        ft.Text("Sin pedidos aún", color=ft.Colors.GREY, text_align=ft.TextAlign.CENTER)
                    )
                state["sig"] = signature
            updated_text.value = (
                f"Actualizado: {datetime.now():%H:%M:%S} · se actualiza cada 15 s"
            )
        except ApiError as ex:
            error_text.value = ex.detail
        finally:
            loading.visible = False
            page.update()

    async def auto_refresh():
        while page.route == "/orders":
            await asyncio.sleep(15)
            if page.route == "/orders":
                await load(True)

    page.run_task(load)
    page.run_task(auto_refresh)

    appbar = ft.AppBar(title=ft.Text("Mis pedidos"))

    return ft.View(
        route="/orders",
        controls=[appbar, ft.SafeArea(ft.Column([
            error_text, loading, updated_text, list_view,
        ], expand=True))],
    )


STATUS_COLORS = {
    "pending": ft.Colors.ORANGE,
    "confirmed": ft.Colors.BLUE,
    "preparing": ft.Colors.AMBER,
    "ready": ft.Colors.GREEN,
    "in_delivery": ft.Colors.TEAL,
    "picked_up": ft.Colors.CYAN,
    "delivered": ft.Colors.GREY,
    "cancelled": ft.Colors.RED,
}


def _order_card(page: ft.Page, o: dict):
    status_color = STATUS_COLORS.get(o["status"], ft.Colors.GREY)
    return ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Text(f"#{str(o['id'])[:8]}", weight=ft.FontWeight.BOLD),
                ft.Container(
                    ft.Text(STATUS_LABELS.get(o["status"], o["status"]), size=11, color=ft.Colors.WHITE),
                    padding=ft.Padding(left=10, top=4, right=10, bottom=4),
                    bgcolor=status_color, border_radius=20,
                ),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Text(f"Total: ${float(o['total']):.2f}", size=14),
                ft.Text(f"Artículos: {len(o.get('items', []))}", size=13, color=ft.Colors.GREY),
                *([ft.Text("Recoger en restaurante", size=12, color=ft.Colors.BLUE)] if o.get("fulfillment_type") == "pickup" else []),
                *([ft.Row([
                    ft.Icon(ft.Icons.STAR, size=14, color=ft.Colors.AMBER),
                    ft.Text("Califica tu pedido", size=12, color=ft.Colors.AMBER),
                ], spacing=4)] if o["status"] == "delivered" else []),
        ]),
        padding=12,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        border_radius=12,
        ink=True,
        on_click=lambda _, oid=o["id"]: page.run_task(page.push_route, f"/order/{oid}"),
    )
