import asyncio
from datetime import datetime, timezone

import flet as ft
from mobile.api import api, ApiError
from mobile.utils import close_dlg, open_dlg, snack, dialog_width


STATUS_ORDER = ["pending", "confirmed", "preparing", "ready"]

STATUS_LABELS = {
    "pending": "Pendiente",
    "confirmed": "Confirmado",
    "preparing": "Preparando",
    "ready": "Listo",
    "in_delivery": "En reparto",
    "picked_up": "Recogido",
    "delivered": "Entregado",
    "cancelled": "Cancelado",
}

STATUS_COLORS = {
    "pending": ft.Colors.AMBER,
    "confirmed": ft.Colors.BLUE,
    "preparing": ft.Colors.ORANGE,
    "ready": ft.Colors.GREEN,
    "in_delivery": ft.Colors.PURPLE,
    "picked_up": ft.Colors.TEAL,
    "delivered": ft.Colors.GREY,
    "cancelled": ft.Colors.RED,
}

_scheduled_alerts: set = set()


def _scheduled_info(o: dict):
    raw = o.get("scheduled_for")
    if not raw:
        return None
    try:
        when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    mins = int((when - datetime.now(timezone.utc)).total_seconds() // 60)
    kind = "recoger" if o.get("fulfillment_type") == "pickup" else "entregar"
    color = ft.Colors.RED if mins <= 30 else (ft.Colors.AMBER if mins <= 60 else ft.Colors.BLUE)
    return {"when": when, "mins": mins, "kind": kind, "color": color}


def _check_scheduled_alerts(page: ft.Page, orders: list):
    for o in orders:
        if not o.get("scheduled_for") or o.get("status") in ("delivered", "cancelled"):
            continue
        info = _scheduled_info(o)
        if not info:
            continue
        mins = info["mins"]
        threshold = 0 if mins <= 0 else (30 if mins <= 30 else (60 if mins <= 60 else None))
        if threshold is None:
            continue
        key = (str(o["id"]), threshold)
        if key in _scheduled_alerts:
            continue
        _scheduled_alerts.add(key)
        when_label = info["when"].astimezone().strftime("%H:%M")
        label = "Falta 1 hora" if threshold == 60 else ("Faltan 30 minutos" if threshold == 30 else "Es la hora programada")
        snack(
            page,
            f"⏰ Pedido #{str(o['id'])[:8]}: {label} para {info['kind']} ({when_label})",
            ft.Colors.ORANGE,
        )


def restaurant_orders_view(page: ft.Page, rid: str):
    loading = ft.ProgressBar(visible=False)
    error_text = ft.Text("", color=ft.Colors.RED)
    updated_text = ft.Text("Se actualiza cada 10 s", size=11, color=ft.Colors.GREY)
    orders_list = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)
    state = {"sig": None}

    async def load(silent: bool = False):
        if not silent:
            loading.visible = True
        error_text.value = ""
        page.update()
        try:
            orders = await api.list_restaurant_orders(rid)
            _check_scheduled_alerts(page, orders)
            signature = tuple(
                (o["id"], o["status"], o.get("delivery_person_id")) for o in orders
            )
            if not silent or signature != state["sig"]:
                orders_list.controls.clear()
                if not orders:
                    orders_list.controls.append(
                        ft.Container(
                            ft.Text("No hay pedidos", color=ft.Colors.GREY, text_align=ft.TextAlign.CENTER),
                            padding=40, alignment=ft.Alignment.CENTER,
                        )
                    )
                for o in orders:
                    orders_list.controls.append(_order_card(page, rid, o, load))
                state["sig"] = signature
            updated_text.value = (
                f"Actualizado: {datetime.now():%H:%M:%S} · se actualiza cada 10 s"
            )
        except ApiError as ex:
            error_text.value = ex.detail
        finally:
            loading.visible = False
            page.update()

    async def auto_refresh():
        while page.route == f"/restaurant-orders/{rid}":
            await asyncio.sleep(10)
            if page.route == f"/restaurant-orders/{rid}":
                await load(True)

    page.run_task(load)
    page.run_task(auto_refresh)

    appbar = ft.AppBar(bgcolor="#1B2F6B", color=ft.Colors.WHITE, 
        leading=ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda e: page.run_task(page.push_route, f"/restaurant/{rid}")),
        title=ft.Text("Pedidos del restaurante"),
    )

    return ft.View(
        route=f"/restaurant-orders/{rid}",
        controls=[
            appbar,
            ft.Column([error_text, loading, updated_text, orders_list], expand=True),
        ]
    )


def _order_card(page: ft.Page, rid: str, o: dict, reload_cb):
    oid = o["id"]
    status = o["status"]
    is_pickup = o.get("fulfillment_type") == "pickup" or o.get("delivery_mode") == "pickup"
    is_own = o.get("delivery_mode") == "own"
    flow = (
        ["pending", "confirmed", "preparing", "ready", "delivered"]
        if is_pickup else
        (["pending", "confirmed", "preparing", "ready", "in_delivery", "delivered"]
         if is_own else STATUS_ORDER)
    )
    items_count = len(o.get("items", []))
    total = float(o.get("total", 0))
    can_advance = status in flow and flow.index(status) < len(flow) - 1
    next_status = flow[flow.index(status) + 1] if can_advance else None

    status_badge = ft.Container(
        content=ft.Text(STATUS_LABELS.get(status, status), size=12, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
        padding=ft.Padding(left=8, right=8, top=3, bottom=3),
        bgcolor=STATUS_COLORS.get(status, ft.Colors.GREY),
        border_radius=12,
    )

    def open_delivery_dialog():
        is_cash = o.get("payment_method") == "cash"
        is_transfer = o.get("payment_method") == "transfer"
        received = ft.TextField(
            label="Dinero que recibes",
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        change_t = ft.Text("Cambio: $0.00", size=14, color=ft.Colors.GREY)
        error_t = ft.Text("", color=ft.Colors.RED, size=12)
        body = [
            ft.Text(f"Pedido #{str(oid)[:8]}", weight=ft.FontWeight.BOLD),
            ft.Row([
                ft.Text("Total", size=16),
                ft.Text(f"${total:.2f}", size=16, weight=ft.FontWeight.BOLD),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ]
        if is_transfer:
            approved = o.get("payment_status") == "approved"
            body.append(ft.Container(
                content=ft.Text(
                    "Pago por transferencia ya validado. No cobres en efectivo."
                    if approved else
                    "Pago por transferencia. El cliente ya pagó; el administrador "
                    "validará la transferencia. No cobres en efectivo.",
                    size=12,
                ),
                padding=10, border_radius=8,
                bgcolor=ft.Colors.GREEN_50 if approved else ft.Colors.BLUE_50,
            ))
        elif is_cash:
            body.extend([received, change_t])
        else:
            body.append(ft.Container(
                content=ft.Text("Pago en línea ya registrado. No cobres en efectivo.", size=12),
                padding=10, border_radius=8, bgcolor=ft.Colors.BLUE_50,
            ))

        def update_change(e=None):
            try:
                value = float(received.value or 0)
            except (TypeError, ValueError):
                value = 0.0
            diff = value - total
            change_t.value = f"Cambio: ${diff:.2f}" if diff >= 0 else f"Faltan: ${abs(diff):.2f}"
            change_t.color = ft.Colors.GREEN if diff >= 0 else ft.Colors.RED
            page.update()

        received.on_change = update_change

        async def confirm(e):
            if is_cash:
                try:
                    value = float(received.value or 0)
                except (TypeError, ValueError):
                    value = 0.0
                if value < total:
                    error_t.value = f"El dinero recibido debe ser al menos ${total:.2f}."
                    page.update()
                    return
            confirm_btn.disabled = True
            try:
                await api.update_restaurant_order_status(rid, oid, "delivered")
                close_dlg(page, dlg)
                if is_cash:
                    value = float(received.value or 0)
                    snack(page, f"Pedido recogido. Cambio: ${value - total:.2f}")
                elif is_transfer:
                    snack(page, "Pedido recogido. Transferencia pendiente de validación.")
                else:
                    snack(page, "Pedido recogido")
                await reload_cb(True)
            except ApiError as ex:
                error_t.value = ex.detail
                confirm_btn.disabled = False
                page.update()

        confirm_btn = ft.FilledButton("Confirmar entrega", on_click=confirm)
        dlg = ft.AlertDialog(
            title=ft.Text("Confirmar entrega"),
            content=ft.Column(body + [error_t], tight=True, width=dialog_width(page), scroll=ft.ScrollMode.AUTO),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: close_dlg(page, dlg)),
                confirm_btn,
            ],
        )
        open_dlg(page, dlg)

    async def advance_status(e):
        current_idx = flow.index(status) if status in flow else -1
        if current_idx < 0 or current_idx >= len(flow) - 1:
            snack(page, "No se puede avanzar más", ft.Colors.RED)
            return
        next_status = flow[current_idx + 1]
        if next_status == "delivered" and is_pickup:
            open_delivery_dialog()
            return
        try:
            await api.update_restaurant_order_status(rid, oid, next_status)
            snack(page, "Pedido recogido" if next_status == "delivered" and is_pickup else f"Pedido {STATUS_LABELS.get(next_status, next_status)}")
            await reload_cb(True)
        except ApiError as ex:
            snack(page, f"Error: {ex.detail}", ft.Colors.RED)

    async def cancel_order(e):
        try:
            await api.update_restaurant_order_status(rid, oid, "cancelled")
            snack(page, "Pedido cancelado")
            await reload_cb(True)
        except ApiError as ex:
            snack(page, f"Error: {ex.detail}", ft.Colors.RED)

    button_label = (
        "Entregar y cobrar" if next_status == "delivered" and is_pickup
        else ("Entregar" if next_status == "delivered" else "Avanzar")
    )

    sched = _scheduled_info(o)
    sched_controls = []
    if sched:
        label = f"Programado para {sched['kind']}: {sched['when'].astimezone():%d/%m %H:%M}"
        label += f" · faltan {sched['mins']} min" if sched["mins"] > 0 else " · ya es la hora"
        sched_controls.append(ft.Text(label, size=12, color=sched["color"]))

    return ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Text(f"#{oid[:8]}", weight=ft.FontWeight.BOLD, size=15),
                status_badge,
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Text(f"{items_count} artículo(s) - ${total:.2f}", size=13),
            *sched_controls,
            ft.Row([
                ft.FilledButton(button_label, on_click=advance_status, disabled=not can_advance, expand=True),
                ft.OutlinedButton("Cancelar", on_click=cancel_order, expand=True),
            ], spacing=8),
        ], spacing=6),
        padding=12,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        border_radius=10,
    )
