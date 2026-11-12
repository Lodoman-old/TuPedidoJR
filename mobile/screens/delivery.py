import asyncio
import json
from datetime import datetime
import flet as ft
import websockets
from mobile.api import api, ApiError
from mobile import secure_auth, background_location
from mobile.config import get_device_location

from mobile.utils import open_dlg, close_dlg, snack, STATUS_LABELS, PAYOUT_STATUS_LABELS, dialog_width
from mobile.map_utils import lat_lng_to_tile, marker_offset, osm_tile_url


TAB_LABELS = ["Disponibles", "Mis repartos", "Ganancias", "Ajustes", "Mandados"]
_available_state = {"ids": set(), "first": True}


def delivery_hub_view(page: ft.Page, is_dp=True):
    content_area = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, spacing=4)
    selected_idx = [0]
    tab_btns = []
    _available_state["ids"] = set()
    _available_state["first"] = True

    def make_tab_btn(idx):
        return ft.Container(
            content=ft.Text(TAB_LABELS[idx], weight=ft.FontWeight.BOLD, size=14),
            padding=ft.Padding(left=16, top=10, right=16, bottom=10),
            border_radius=ft.BorderRadius(top_left=10, top_right=10, bottom_left=0, bottom_right=0),
            ink=True,
            data=idx,
            on_click=lambda e: page.run_task(switch_tab, e.control.data),
        )

    for i in range(5):
        tab_btns.append(make_tab_btn(i))

    tab_bar = ft.Row(tab_btns, scroll=ft.ScrollMode.AUTO, spacing=0)

    def update_tab_bar():
        for i, btn in enumerate(tab_btns):
            btn.bgcolor = ft.Colors.PRIMARY_CONTAINER if i == selected_idx[0] else ft.Colors.SURFACE_CONTAINER_HIGH
            btn.content.color = ft.Colors.ON_PRIMARY_CONTAINER if i == selected_idx[0] else ft.Colors.ON_SURFACE

    async def switch_tab(idx):
        selected_idx[0] = idx
        update_tab_bar()
        if not is_dp:
            content_area.controls = [ft.Text("No eres repartidor", color=ft.Colors.GREY, size=16, text_align=ft.TextAlign.CENTER)]
            page.update()
            return
        if idx == 0:
            await load_available(page, content_area)
        elif idx == 1:
            await load_my_orders(page, content_area)
        elif idx == 2:
            await load_payouts(page, content_area)
        elif idx == 3:
            await load_settings(page, content_area)
        elif idx == 4:
            await load_mandados(page, content_area)

    update_tab_bar()

    if is_dp:
        page.run_task(switch_tab, 0)

    async def auto_refresh():
        while page.route == "/delivery":
            await asyncio.sleep(15)
            if page.route != "/delivery":
                break
            if selected_idx[0] == 0:
                await load_available(page, content_area)
            else:
                await check_new_available(page)

    page.run_task(auto_refresh)

    appbar = ft.AppBar(bgcolor="#1B2F6B", color=ft.Colors.WHITE, 
        title=ft.Text("Repartidor"),
        actions=[
            ft.IconButton(ft.Icons.MY_LOCATION, on_click=lambda e: page.run_task(page.push_route, "/delivery/location")),
            ft.IconButton(ft.Icons.REFRESH, on_click=lambda e: page.run_task(switch_tab, selected_idx[0])),
        ],
    )

    return ft.View(
        route="/delivery",
        controls=[appbar, ft.SafeArea(ft.Column([tab_bar, ft.Divider(height=0), content_area], expand=True))],
    )


def _detect_new_available(page: ft.Page, orders: list):
    ids = {o["id"] for o in orders}
    if not _available_state["first"]:
        new_ids = ids - _available_state["ids"]
        if new_ids:
            snack(
                page,
                f"🔔 {len(new_ids)} pedido(s) nuevo(s) disponible(s)",
                ft.Colors.ORANGE,
            )
    _available_state["ids"] = ids
    _available_state["first"] = False


async def check_new_available(page: ft.Page):
    """Revisa si hay pedidos nuevos sin cambiar la pestaña visible."""
    try:
        ready = await api.list_available_delivery_orders()
    except ApiError:
        return
    _detect_new_available(page, ready)


async def load_available(page: ft.Page, content_area: ft.Column):
    loading = ft.ProgressBar()
    content_area.controls = [loading]
    page.update()
    try:
        ready = await api.list_available_delivery_orders()
        _detect_new_available(page, ready)

        now = datetime.now().strftime("%H:%M:%S")
        header = ft.Row([
            ft.Text(f"Actualizado: {now}", size=11, color=ft.Colors.GREY),
            ft.Text("Se revisa cada 15 s", size=11, color=ft.Colors.GREY),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
        cards = []
        if not ready:
            cards.append(ft.Text("No hay pedidos disponibles", color=ft.Colors.GREY, text_align=ft.TextAlign.CENTER))
        for o in ready:
            cards.append(_available_order_card(page, o, content_area))
        content_area.controls = [
            header,
            ft.ListView(controls=cards, spacing=8, padding=10, expand=True),
        ]
    except ApiError as ex:
        content_area.controls = [ft.Text(f"Error: {ex.detail}", color=ft.Colors.RED)]
    finally:
        page.update()


def _available_order_card(page: ft.Page, o: dict, content_area: ft.Column):
    async def accept(e):
        try:
            await api.accept_delivery(o["id"])
            background_location.set_enabled(True)
            snack(page, "Pedido aceptado")
            await load_available(page, content_area)
        except ApiError as ex:
            snack(page, f"Error: {ex.detail}", ft.Colors.RED)
            page.update()

    return ft.Container(
        content=ft.Column([
        ft.Row([
            ft.Text(f"#{str(o['id'])[:8]}", weight=ft.FontWeight.BOLD),
            ft.Container(
                ft.Text(STATUS_LABELS.get(o["status"], o["status"]), size=11, color=ft.Colors.WHITE),
                padding=ft.Padding(left=10, top=4, right=10, bottom=4),
                bgcolor=ft.Colors.GREEN if o["status"] == "ready" else ft.Colors.AMBER,
                border_radius=20,
            ),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Text(f"Total: ${float(o['total']):.2f}", size=14),
            ft.Text(
                " · ".join(filter(None, [
                    o.get("restaurant_name"),
                    f"{o['distance_km']} km" if o.get("distance_km") is not None else None,
                    f"~{o['eta_min']} min" if o.get("eta_min") is not None else None,
                ])) or "Activa tu ubicación para ver la distancia",
                size=12, color=ft.Colors.BLUE,
            ),
            ft.Text(f"Artículos: {len(o.get('items', []))}", size=13, color=ft.Colors.GREY),
            ft.FilledTonalButton("Aceptar pedido", on_click=accept),
        ]),
        padding=12,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        border_radius=12,
    )


async def load_my_orders(page: ft.Page, content_area: ft.Column):
    loading = ft.ProgressBar()
    content_area.controls = [loading]
    page.update()
    try:
        orders = await api.list_delivery_orders()
        cards = []
        if not orders:
            cards.append(ft.Text("No tienes repartos asignados", color=ft.Colors.GREY, text_align=ft.TextAlign.CENTER))
        for o in orders:
            cards.append(_my_order_card(page, o, content_area))
        content_area.controls = [ft.ListView(controls=cards, spacing=8, padding=10, expand=True)]
    except ApiError as ex:
        content_area.controls = [ft.Text(f"Error: {ex.detail}", color=ft.Colors.RED)]
    finally:
        page.update()


def _my_order_card(page: ft.Page, o: dict, content_area: ft.Column):
    status_colors = {
        "in_delivery": ft.Colors.BLUE,
        "picked_up": ft.Colors.TEAL,
        "delivered": ft.Colors.GREEN,
        "cancelled": ft.Colors.RED,
    }
    color = status_colors.get(o["status"], ft.Colors.GREY)
    payment = o.get("payment_method")
    if payment == "transfer":
        payment_label = (
            "Transferencia validada por el administrador"
            if o.get("payment_status") == "approved"
            else "Transferencia pendiente de validar"
        )
    elif payment == "cash":
        payment_label = "Pago en efectivo"
    else:
        payment_label = "Pago en línea"

    actions = []
    if o["status"] == "in_delivery":
        async def pick_up(e):
            try:
                await api.pickup_delivery(o["id"])
                snack(page, "Pedido recogido")
                await load_my_orders(page, content_area)
            except ApiError as ex:
                snack(page, f"Error: {ex.detail}", ft.Colors.RED)
                page.update()
        actions.append(
            ft.FilledButton("Recoger pedido", on_click=pick_up)
        )
        async def request_advance(e):
            try:
                advance = await api.request_cash_advance(o["id"])
                snack(page, f"Avance solicitado: ${float(advance['amount']):.2f}")
            except ApiError as ex:
                snack(page, f"Error: {ex.detail}", ft.Colors.RED)
                page.update()
        actions.append(
            ft.OutlinedButton("Pedir avance", icon=ft.Icons.PAYMENTS, on_click=request_advance)
        )
        actions.append(
            ft.FilledTonalButton("Ver ruta", on_click=lambda _, oid=o["id"]: page.run_task(page.push_route, f"/delivery/track/{oid}"))
        )
    elif o["status"] == "picked_up":
        async def deliver(e):
            total = float(o.get("total") or 0)
            earnings = float(o.get("delivery_earnings") or 0)
            owed = max(0.0, total - earnings)
            payment = o.get("payment_method")
            is_cash = payment == "cash"
            is_transfer = payment == "transfer"

            received = ft.TextField(
                label="Dinero que recibes",
                keyboard_type=ft.KeyboardType.NUMBER,
            )
            change_t = ft.Text("Cambio: $0.00", size=14, color=ft.Colors.GREY)
            error_t = ft.Text("", color=ft.Colors.RED, size=12)
            body = [
                ft.Text(f"Pedido #{str(o['id'])[:8]}", weight=ft.FontWeight.BOLD),
                ft.Row([
                    ft.Text("Total", size=16),
                    ft.Text(f"${total:.2f}", size=16, weight=ft.FontWeight.BOLD),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Text(f"Tu ganancia de reparto: ${earnings:.2f}", size=12, color=ft.Colors.GREEN),
            ]
            if is_transfer:
                approved = o.get("payment_status") == "approved"
                body.append(ft.Container(
                    content=ft.Text(
                        "Pago por transferencia ya validado por el administrador. "
                        "No cobres en efectivo."
                        if approved else
                        "Pago por transferencia. El cliente ya pagó; el administrador "
                        "validará la transferencia. No cobres en efectivo.",
                        size=12,
                    ),
                    padding=10, border_radius=8,
                    bgcolor=ft.Colors.GREEN_50 if approved else ft.Colors.BLUE_50,
                ))
            elif not is_cash:
                body.append(ft.Container(
                    content=ft.Text(
                        "Pago en línea ya registrado. No cobres en efectivo.",
                        size=12,
                    ),
                    padding=10, border_radius=8, bgcolor=ft.Colors.BLUE_50,
                ))
            else:
                body.append(ft.Text(
                    f"Debes entregar ${owed:.2f} a la plataforma/restaurante.",
                    size=11, color=ft.Colors.GREY,
                ))
                body.extend([received, change_t])

            def update_change(e=None):
                try:
                    value = float(received.value or 0)
                except (TypeError, ValueError):
                    value = 0.0
                diff = value - total
                change_t.value = (
                    f"Cambio: ${diff:.2f}" if diff >= 0
                    else f"Faltan: ${abs(diff):.2f}"
                )
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
                    await api.deliver_delivery(o["id"])
                    background_location.set_enabled(True)
                    close_dlg(page, dlg)
                    if is_cash:
                        value = float(received.value or 0)
                        snack(page, f"Pedido entregado. Cambio: ${value - total:.2f}")
                    elif is_transfer:
                        snack(
                            page,
                            "Pedido entregado. Transferencia ya validada."
                            if o.get("payment_status") == "approved"
                            else "Pedido entregado. Transferencia pendiente de validación.",
                        )
                    else:
                        snack(page, "Pedido entregado")
                    await load_my_orders(page, content_area)
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

        actions.append(
            ft.FilledButton("Entregar pedido", on_click=deliver)
        )

    return ft.Container(
        content=ft.Column([
        ft.Row([
            ft.Text(f"#{str(o['id'])[:8]}", weight=ft.FontWeight.BOLD),
            ft.Container(
                ft.Text(STATUS_LABELS.get(o["status"], o["status"]), size=11, color=ft.Colors.WHITE),
                padding=ft.Padding(left=10, top=4, right=10, bottom=4),
                bgcolor=color,
                border_radius=20,
            ),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Text(f"Total: ${float(o['total']):.2f}", size=14),
            ft.Text(o.get("delivery_address") or "", size=12, color=ft.Colors.GREY),
            ft.Text(f"Pago: {payment_label}", size=12, color=ft.Colors.BLUE),
            ft.Text(f"Ganancia reparto: ${float(o.get('delivery_earnings', 0)):.2f}", size=13, color=ft.Colors.GREEN),
            ft.Row(actions) if actions else ft.Container(),
        ]),
        padding=12,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        border_radius=12,
    )


async def load_payouts(page: ft.Page, content_area: ft.Column):
    loading = ft.ProgressBar()
    content_area.controls = [loading]
    page.update()
    try:
        earnings = await api.get_delivery_earnings()
        payouts = await api.list_delivery_payouts()

        summary = ft.Container(
            content=ft.Column([
                ft.Text("Resumen de ganancias", size=18, weight=ft.FontWeight.BOLD),
                ft.Row([
                    ft.Column([
                        ft.Text("Total ganado", size=10, color=ft.Colors.GREY),
                        ft.Text(f"${float(earnings['total_earned']):.2f}", size=15, color=ft.Colors.PRIMARY, weight=ft.FontWeight.BOLD),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2, expand=True),
                    ft.Column([
                        ft.Text("Pte. plataforma", size=10, color=ft.Colors.GREY),
                        ft.Text(f"${float(earnings['total_pending_from_platform']):.2f}", size=15, color=ft.Colors.AMBER, weight=ft.FontWeight.BOLD),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2, expand=True),
                ], alignment=ft.MainAxisAlignment.SPACE_AROUND),
                ft.Row([
                    ft.Column([
                        ft.Text("Deuda", size=10, color=ft.Colors.GREY),
                        ft.Text(f"${float(earnings['total_pending_debt']):.2f}", size=15, color=ft.Colors.RED, weight=ft.FontWeight.BOLD),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2, expand=True),
                    ft.Column([
                        ft.Text("Pagado", size=10, color=ft.Colors.GREY),
                        ft.Text(f"${float(earnings['total_paid']):.2f}", size=15, color=ft.Colors.GREEN, weight=ft.FontWeight.BOLD),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2, expand=True),
                ], alignment=ft.MainAxisAlignment.SPACE_AROUND),
                ft.Row([
                    ft.Column([
                        ft.Text("Avances", size=10, color=ft.Colors.GREY),
                        ft.Text(f"${float(earnings.get('total_advance_debt', 0)):.2f}", size=13, color=ft.Colors.ORANGE, weight=ft.FontWeight.BOLD),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2, expand=True),
                    ft.Column([
                        ft.Text("Transf. por confirmar", size=10, color=ft.Colors.GREY),
                        ft.Text(f"${float(earnings.get('total_pending_confirmation', 0)):.2f}", size=13, color=ft.Colors.GREY_700, weight=ft.FontWeight.BOLD),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2, expand=True),
                ], alignment=ft.MainAxisAlignment.SPACE_AROUND),
                ft.Divider(height=8),
                ft.Text(f"Entregas completadas: {earnings['total_deliveries']}", size=13, color=ft.Colors.GREY),
            ]),
            padding=15,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
            border_radius=12,
            margin=ft.Margin(left=0, top=0, right=0, bottom=10),
        )

        cards = [summary]

        pending_payouts = float(earnings.get('total_pending_payouts', 0))
        available = (
            float(earnings['total_earned'])
            - float(earnings['total_paid'])
            - pending_payouts
            - float(earnings['total_pending_debt'])
            - float(earnings.get('total_advance_debt', 0))
            - float(earnings.get('total_pending_confirmation', 0))
        )
        if pending_payouts > 0:
            cards.append(ft.Text(
                f"Liquidación en proceso: ${pending_payouts:.2f}",
                size=12, color=ft.Colors.AMBER, weight=ft.FontWeight.BOLD,
            ))
        if available > 0:
            cards.append(
                ft.Container(
                    content=ft.Button(
                        f"Solicitar liquidación — ${available:.2f}",
                        color=ft.Colors.WHITE,
                        bgcolor=ft.Colors.GREEN,
                        on_click=lambda e: page.run_task(request_payout_action, page, content_area),
                        expand=True,
                    ),
                    padding=ft.Padding(left=0, top=0, right=0, bottom=5),
                )
            )

        if earnings.get("orders"):
            cards.append(ft.Text("Últimas entregas", size=14, weight=ft.FontWeight.BOLD))
            for o in earnings["orders"]:
                pm_label = {
                    "cash": "Efectivo",
                    "mp": "Mercado Pago",
                    "transfer": "Transferencia",
                }.get(o.get("payment_method"), "Efectivo")
                pm_color = ft.Colors.BLUE if o.get("payment_method") in ("mp", "transfer") else ft.Colors.AMBER
                cards.append(ft.Container(
                    content=ft.Row([
                        ft.Column([
                            ft.Text(f"#{str(o['id'])[:8]}", size=12, weight=ft.FontWeight.BOLD),
                            ft.Row([
                                ft.Text(pm_label, size=10, color=pm_color),
                                ft.Text(o.get("placed_at", "")[:10], size=10, color=ft.Colors.GREY),
                            ], spacing=4),
                        ], spacing=2, expand=True),
                        ft.Column([
                            ft.Text(f"${float(o['total']):.2f}", size=13),
                            ft.Text(f"+${float(o['delivery_earnings']):.2f}", size=12, color=ft.Colors.GREEN),
                        ], horizontal_alignment=ft.CrossAxisAlignment.END, spacing=2),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    padding=10,
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
                    border_radius=8,
                ))

        if payouts:
            cards.append(ft.Text("Historial de pagos", size=14, weight=ft.FontWeight.BOLD, margin=ft.Margin(top=10, left=0, bottom=0, right=0)))
            for p in payouts:
                cards.append(_payout_card(p))
        else:
            cards.append(ft.Text("Sin historial de pagos", color=ft.Colors.GREY, text_align=ft.TextAlign.CENTER))

        content_area.controls = [ft.ListView(
            controls=cards,
            spacing=8,
            padding=10,
            expand=True,
        )]
    except ApiError as ex:
        content_area.controls = [ft.Text(f"Error: {ex.detail}", color=ft.Colors.RED)]
    finally:
        page.update()


async def request_payout_action(page: ft.Page, content_area: ft.Column):
    try:
        payout = await api.request_payout()
        page.show_dialog(ft.SnackBar(ft.Text(f"Liquidación generada: ${float(payout['total_earnings']):.2f}"), bgcolor=ft.Colors.GREEN))
        await load_payouts(page, content_area)
    except ApiError as ex:
        page.show_dialog(ft.SnackBar(ft.Text(f"Error: {ex.detail}"), bgcolor=ft.Colors.RED))


def _payout_card(p: dict):
    status_color = {
        "pending": ft.Colors.AMBER,
        "paid": ft.Colors.BLUE,
        "confirmed": ft.Colors.GREEN,
        "cancelled": ft.Colors.RED,
    }.get(p["status"], ft.Colors.GREY)

    code_row = []
    if p["status"] == "pending" and p.get("confirmation_code"):
        code_row = [
            ft.Divider(),
            ft.Row([
                ft.Text("Código confirmación:", size=12, color=ft.Colors.GREY),
                ft.Text(p["confirmation_code"], size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.TEAL, selectable=True),
            ]),
        ]

    return ft.Container(
        content=ft.Column([
        ft.Row([
            ft.Text(f"{p['period_start']} → {p['period_end']}", weight=ft.FontWeight.BOLD, size=13),
            ft.Container(
                ft.Text(PAYOUT_STATUS_LABELS.get(p["status"], p["status"]), size=11, color=ft.Colors.WHITE),
                padding=ft.Padding(left=8, top=3, right=8, bottom=3),
                bgcolor=status_color,
                border_radius=20,
            ),
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Text(f"${float(p['total_earnings']):.2f} ({p['orders_count']} repartos)", size=14, color=ft.Colors.GREEN),
            ft.Text(f"Método: {p['payout_method']}", size=12, color=ft.Colors.GREY),
            *code_row,
        ]),
        padding=12,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        border_radius=12,
    )


async def load_settings(page: ft.Page, content_area: ft.Column):
    loading = ft.ProgressBar()
    content_area.controls = [loading]
    page.update()
    try:
        prof = await api.get_delivery_profile()

        async def toggle(e):
            try:
                await api.set_delivery_availability(e.control.value)
                background_location.set_enabled(bool(e.control.value))
                snack(page, "Disponibilidad actualizada")
            except ApiError as ex:
                snack(page, f"Error: {ex.detail}", ft.Colors.RED)
                e.control.value = not e.control.value
            page.update()

        avail_switch = ft.Switch(
            label="Disponible para repartos",
            value=prof["is_available"],
            on_change=lambda e: page.run_task(toggle, e),
        )

        bio_switch = ft.Switch(label="Entrar con huella o rostro", value=False)
        bio_msg = ft.Text("", size=11, color=ft.Colors.GREY)
        bio_card = ft.Container(
            content=ft.Column([
                ft.Text("Seguridad", size=14, weight=ft.FontWeight.BOLD),
                bio_switch,
                bio_msg,
            ], spacing=4),
            visible=False,
        )

        async def load_biometric():
            if not await secure_auth.biometric_available():
                return
            bio_card.visible = True
            bio_switch.value = await secure_auth.is_biometric_enabled()
            page.update()

        async def toggle_biometric(e):
            enabled = bool(e.control.value)
            if enabled:
                ok = await secure_auth.authenticate("Activa el ingreso con huella o rostro")
                if not ok:
                    bio_switch.value = False
                    bio_msg.value = "No se pudo verificar la huella o rostro."
                    bio_msg.color = ft.Colors.RED
                    page.update()
                    return
                if api.token:
                    try:
                        me = await api.get_profile()
                        await secure_auth.save_session(api.token, me.get("email", ""), me.get("name", ""))
                    except Exception:
                        await secure_auth.save_session(api.token)
                await secure_auth.set_biometric(True)
                bio_msg.value = "Ingreso con huella activado."
                bio_msg.color = ft.Colors.GREEN
            else:
                await secure_auth.set_biometric(False)
                bio_msg.value = "Ingreso con huella desactivado."
                bio_msg.color = ft.Colors.GREY
            page.update()

        bio_switch.on_change = lambda e: page.run_task(toggle_biometric, e)
        page.run_task(load_biometric)

        debt = float(prof.get("pending_platform_debt", 0))
        debt_text = ft.Text(f"Deuda pendiente: ${debt:.2f}", size=12, color=ft.Colors.RED if debt > 0 else ft.Colors.GREY)
        vehicle = (prof.get("vehicle_type") or "").lower()
        vehicle_label = {
            "motorcycle": "Moto",
            "bicycle": "Bicicleta",
            "car": "Auto",
            "walking": "A pie",
        }.get(vehicle, vehicle or "—")

        payout_method = ["cash"]

        def build_settings(method=None):
            v = method or prof.get("payout_method") or "cash"
            payout_method[0] = v
            show_bank = v == "transfer"
            content_area.controls = [
                avail_switch,
                ft.Text("Con disponible activo, la app comparte tu ubicación también en segundo plano. Permite la ubicación “Todo el tiempo” en Android.", size=11, color=ft.Colors.GREY),
                ft.Text("Repartidor", size=15, weight=ft.FontWeight.BOLD),
                ft.Text(f"Vehículo: {vehicle_label}", size=12, color=ft.Colors.GREY),
                ft.Text(f"Calificación: {prof['rating']}⭐ · {prof['total_deliveries']} repartos", size=12),
                debt_text,
                bio_card,
                ft.Divider(height=1),
                ft.Text("Configuración de pago", size=14, weight=ft.FontWeight.BOLD),
                ft.Row([
                    ft.Button("Efectivo", style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN if v == "cash" else ft.Colors.SURFACE_CONTAINER_HIGH, color=ft.Colors.WHITE if v == "cash" else ft.Colors.ON_SURFACE, padding=ft.Padding(12, 6, 12, 6)), on_click=lambda e: rebuild_settings("cash")),
                    ft.Button("Transferencia", style=ft.ButtonStyle(bgcolor=ft.Colors.GREEN if v == "transfer" else ft.Colors.SURFACE_CONTAINER_HIGH, color=ft.Colors.WHITE if v == "transfer" else ft.Colors.ON_SURFACE, padding=ft.Padding(12, 6, 12, 6)), on_click=lambda e: rebuild_settings("transfer")),
                ], spacing=8),
                ft.Dropdown(
                    label="Frecuencia de pago",
                    value=str(
                        prof["payout_frequency_days"]
                        if prof.get("payout_frequency_days") is not None else 7
                    ),
                    options=[
                        ft.DropdownOption(key="0", text="Otro: a demanda (varias veces al día)"),
                        ft.DropdownOption(key="1", text="Diario"),
                        ft.DropdownOption(key="3", text="Cada 3 días"),
                        ft.DropdownOption(key="7", text="Cada 7 días"),
                        ft.DropdownOption(key="15", text="Cada 15 días"),
                        ft.DropdownOption(key="30", text="Cada 30 días"),
                    ],
                    key="freq_dd",
                ),
                ft.Text(
                    "“Otro” te permite solicitar varias veces al día cuando tengas saldo.",
                    size=11, color=ft.Colors.GREY,
                ),
                ft.Container(
                    content=ft.Column([
                        ft.TextField(label="Nombre del banco", value=prof.get("bank_name") or "", text_size=13),
                        ft.TextField(label="Titular de cuenta", value=prof.get("bank_account_holder") or "", text_size=13),
                        ft.TextField(label="CLABE", value=prof.get("bank_clabe") or "", text_size=13),
                    ], spacing=4),
                    visible=show_bank,
                ),
                ft.ProgressBar(visible=False),
                ft.Text("", size=12, color=ft.Colors.GREEN),
                ft.FilledButton("Guardar configuración", style=ft.ButtonStyle(padding=ft.Padding(16, 8, 16, 8)), on_click=lambda e: page.run_task(save_profile, e)),
            ]

        def rebuild_settings(method):
            payout_method[0] = method
            build_settings(method)
            page.update()

        async def save_profile(e):
            ctrls = content_area.controls
            freq_dd = [c for c in ctrls if getattr(c, 'key', None) == 'freq_dd'][0]
            bank_col = ctrls[7]
            bank_fields = bank_col.content.controls if bank_col.content else []
            bank_name = bank_fields[0].value if len(bank_fields) > 0 else None
            bank_holder = bank_fields[1].value if len(bank_fields) > 1 else None
            bank_clabe = bank_fields[2].value if len(bank_fields) > 2 else None
            saving_bar = ctrls[8]
            status_t = ctrls[9]
            saving_bar.visible = True
            status_t.value = ""
            page.update()
            try:
                kwargs = {
                    "payout_method": payout_method[0],
                    "payout_frequency_days": int(freq_dd.value),
                    "bank_name": bank_name or None,
                    "bank_account_holder": bank_holder or None,
                    "bank_clabe": bank_clabe or None,
                }
                await api.update_delivery_profile(**kwargs)
                status_t.value = "Configuración guardada"
            except ApiError as ex:
                status_t.value = f"Error: {ex.detail}"
                status_t.color = ft.Colors.RED
            finally:
                saving_bar.visible = False
                page.update()

        build_settings()
    except ApiError as ex:
        content_area.controls = [ft.Text(f"Error: {ex.detail}", color=ft.Colors.RED)]
    finally:
        page.update()


async def load_mandados(page: ft.Page, content_area: ft.Column):
    loading = ft.ProgressBar()
    content_area.controls = [loading]
    page.update()
    try:
        mandados = await api.list_mandados()
    except ApiError as ex:
        content_area.controls = [ft.Text(f"Error: {ex.detail}", color=ft.Colors.RED)]
        page.update()
        return

    available = [m for m in mandados if m["status"] == "pending" and not m.get("delivery_person_id")]
    active = [m for m in mandados if m.get("delivery_person_id") and m["status"] in ("accepted", "purchased")]

    cards = []

    if available:
        cards.append(ft.Text("Mandados disponibles", size=16, weight=ft.FontWeight.BOLD))
        for m in available:
            cards.append(_mandado_card(page, m, "available", content_area))
    else:
        cards.append(ft.Text("No hay mandados disponibles", color=ft.Colors.GREY))

    if active:
        cards.append(ft.Divider())
        cards.append(ft.Text("Mis mandados activos", size=16, weight=ft.FontWeight.BOLD))
        for m in active:
            cards.append(_mandado_card(page, m, m["status"], content_area))
    else:
        cards.append(ft.Divider())
        cards.append(ft.Text("No tienes mandados activos", color=ft.Colors.GREY))

    content_area.controls = [ft.ListView(controls=cards, spacing=10, padding=10, expand=True)]
    page.update()


def _mandado_card(page: ft.Page, m: dict, mode: str, content_area: ft.Column) -> ft.Container:
    status_colors = {"pending": ft.Colors.ORANGE, "accepted": ft.Colors.BLUE, "purchased": ft.Colors.TEAL, "completed": ft.Colors.GREEN}
    desc = ft.Text(m["description"], size=14, weight=ft.FontWeight.BOLD)
    budget = ft.Text(f"Presupuesto: ${float(m['estimated_budget']):.2f} | Envío: ${float(m['delivery_fee']):.2f}", size=12)
    fees = ft.Text(f"Riesgo: ${float(m['risk_fee']):.2f} | Plataforma: ${float(m['platform_fee']):.2f}", size=12, color=ft.Colors.GREY)
    total = ft.Text(f"Total estimado: ${float(m['estimated_total']):.2f}", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN)
    status = ft.Text(f"Estado: {STATUS_LABELS.get(m['status'], m['status'])}", size=12, color=status_colors.get(m["status"], ft.Colors.GREY))

    body = ft.Column([desc, budget, fees, total, status], spacing=4)

    if mode == "available":
        async def accept(e):
            e.control.disabled = True
            page.update()
            try:
                await api.accept_mandado(m["id"])
                snack(page, "Mandado aceptado")
                await load_mandados(page, content_area)
            except ApiError as ex:
                snack(page, f"Error: {ex.detail}", ft.Colors.RED)
                e.control.disabled = False
                page.update()
        body.controls.append(ft.FilledButton("Aceptar mandado", on_click=accept))

    elif mode == "accepted":
        mid = m["id"]
        async def mark_purchased(e):
            total_input = ft.TextField(label="Total de productos ($)", keyboard_type=ft.KeyboardType.NUMBER)
            url_input = ft.TextField(label="URL del comprobante (o vacío para subir foto)")
            status_t = ft.Text("")

            async def submit(e):
                if not total_input.value:
                    status_t.value = "Ingresa el total"
                    page.update()
                    return
                photo_url = url_input.value
                try:
                    await api.purchase_mandado(str(mid), float(total_input.value), photo_url or "")
                    close_dlg(page, dlg)
                    snack(page, "¡Compra registrada!")
                    await load_mandados(page, content_area)
                except ApiError as ex:
                    status_t.value = f"Error: {ex.detail}"
                    page.update()

            dlg = ft.AlertDialog(
                title=ft.Text("Marcar como comprado"),
                content=ft.Column([total_input, url_input, status_t, ft.FilledButton("Confirmar", on_click=submit)], tight=True, width=dialog_width(page)),
                actions=[ft.TextButton("Cancelar", on_click=lambda e: close_dlg(page, dlg))],
            )
            open_dlg(page, dlg)

        body.controls.append(ft.FilledButton("Marcar como comprado", on_click=mark_purchased))

    elif mode == "purchased":
        async def deliver(e):
            e.control.disabled = True
            page.update()
            try:
                await api.deliver_mandado(str(m["id"]))
                snack(page, "Mandado entregado")
                await load_mandados(page, content_area)
            except ApiError as ex:
                snack(page, f"Error: {ex.detail}", ft.Colors.RED)
                e.control.disabled = False
                page.update()
        body.controls.append(ft.FilledButton("Entregar mandado", on_click=deliver))

    return ft.Container(
        content=body,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        border_radius=10,
        padding=12,
        margin=ft.Margin(0, 0, 0, 8),
    )


def deliver_location_view(page: ft.Page):
    lat_input = ft.TextField(label="Latitud", value="20.644", on_change=lambda e: _update_map_from_inputs())
    lng_input = ft.TextField(label="Longitud", value="-100.993", on_change=lambda e: _update_map_from_inputs())
    speed_input = ft.TextField(label="Velocidad (km/h, opcional)")
    status_text = ft.Text("", color=ft.Colors.GREEN)
    loading = ft.ProgressBar(visible=False)

    map_tile = ft.Image(src="https://tile.openstreetmap.org/0/0/0.png", fit=ft.BoxFit.FILL)
    marker = ft.Container(
        content=ft.Icon(ft.Icons.LOCATION_ON, size=36, color=ft.Colors.RED),
        width=36, height=36,
        alignment="center",
    )
    MAP_SIZE = 300
    map_bg = ft.Container(
        content=ft.Stack(
            controls=[map_tile, marker],
            width=MAP_SIZE, height=MAP_SIZE,
        ),
        width=MAP_SIZE, height=MAP_SIZE,
        border_radius=12, clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )
    map_display = ft.Container(
        content=ft.Text("Ingresa coordenadas para ver el mapa", color=ft.Colors.GREY, text_align=ft.TextAlign.CENTER),
        height=MAP_SIZE, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH, border_radius=12,
        alignment="center",
    )

    def _update_map(lat: float, lng: float):
        try:
            x_tile, y_tile = lat_lng_to_tile(lat, lng)
            tile_url = osm_tile_url(x_tile, y_tile)
            map_tile.src = tile_url
            px, py = marker_offset(lat, lng, x_tile, y_tile)
            marker.top = max(0, py - 18)
            marker.left = max(0, px - 18)
            map_display.content = map_bg
        except Exception:
            map_display.content = ft.Text("Coordenadas inválidas", color=ft.Colors.RED, text_align=ft.TextAlign.CENTER)
        page.update()

    def _update_map_from_inputs():
        try:
            lat = float(lat_input.value)
            lng = float(lng_input.value)
            _update_map(lat, lng)
        except ValueError:
            pass

    async def update(e):
        loading.visible = True
        status_text.value = ""
        page.update()
        try:
            lat = float(lat_input.value)
            lng = float(lng_input.value)
            speed = float(speed_input.value) if speed_input.value else None
            await api.update_location(lat, lng, speed)
            status_text.value = "Ubicación actualizada"
        except ValueError:
            status_text.value = "Coordenadas inválidas"
        except ApiError as ex:
            status_text.value = ex.detail
        finally:
            loading.visible = False
            page.update()

    async def use_device_location(e=None):
        loc = get_device_location()
        if not loc:
            status_text.value = "El GPS todavía no tiene ubicación. Revisa los permisos del dispositivo."
            page.update()
            return
        lat_input.value = f"{float(loc['lat']):.7f}"
        lng_input.value = f"{float(loc['lng']):.7f}"
        if loc.get("speed_kmh") is not None:
            speed_input.value = f"{float(loc['speed_kmh']):.1f}"
        _update_map(float(loc["lat"]), float(loc["lng"]))
        await update(e)

    _update_map_from_inputs()

    return ft.View(
        route="/delivery/location",
        controls=[
            ft.AppBar(bgcolor="#1B2F6B", color=ft.Colors.WHITE, title=ft.Text("Actualizar ubicación")),
            ft.SafeArea(ft.Column([
                lat_input, lng_input, speed_input,
                map_display,
                loading, status_text,
                ft.FilledTonalButton("Usar ubicación del dispositivo", on_click=lambda e: page.run_task(use_device_location, e)),
                ft.FilledButton("Actualizar", on_click=update),
                ft.TextButton("Volver", on_click=lambda e: page.run_task(page.push_route, "/delivery")),
            ], scroll=ft.ScrollMode.AUTO, horizontal_alignment=ft.CrossAxisAlignment.CENTER))
        ]
    )


def delivery_track_view(page: ft.Page, oid: str):
    status_text = ft.Text("En reparto", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.TEAL)
    ws_status = ft.Text("Conectando...", size=12, color=ft.Colors.GREY)
    ws = None
    running = True

    async def ws_connect():
        nonlocal ws
        url = f"{api.ws_url}/delivery/{oid}/location"
        try:
            ws = await websockets.connect(url)
            await ws.send(json.dumps({"token": api.token}))
            ws_status.value = "Conectado"
            page.update()
            while running:
                msg = await ws.recv()
        except Exception as ex:
            ws_status.value = f"Desconectado: {ex}"
            page.update()

    async def send_location(e):
        nonlocal ws
        if not ws:
            ws_status.value = "No conectado"
            page.update()
            return
        import random
        lat = 20.644 + random.uniform(-0.01, 0.01)
        lng = -100.993 + random.uniform(-0.01, 0.01)
        speed = random.uniform(10, 40)
        payload = {"type": "location", "lat": lat, "lng": lng, "speed_kmh": speed}
        try:
            await ws.send(json.dumps(payload))
            ws_status.value = "Ubicación enviada"
        except Exception as ex:
            ws_status.value = f"Error: {ex}"
        page.update()

    page.run_task(ws_connect)

    return ft.View(
        route=f"/delivery/track/{oid}",
        controls=[
            ft.AppBar(bgcolor="#1B2F6B", color=ft.Colors.WHITE, title=ft.Text(f"Reparto #{oid[:8]}")),
            ft.SafeArea(ft.Column([
                status_text, ws_status,
                ft.Divider(),
                ft.FilledButton("Enviar ubicación", on_click=send_location),
                ft.TextButton("Volver", on_click=lambda e: page.run_task(page.push_route, "/delivery")),
            ], scroll=ft.ScrollMode.AUTO, horizontal_alignment=ft.CrossAxisAlignment.CENTER))
        ]
    )