import asyncio
import json
import time
from urllib.parse import quote

import flet as ft
from mobile.api import api, ApiError
from mobile.screens.orders import STATUS_COLORS
from mobile.utils import snack, STATUS_LABELS
from mobile.map_widget import map_image, update_map


ACTIVE_STATUSES = ("pending", "confirmed", "preparing", "ready", "in_delivery", "picked_up")


def order_detail_view(page: ft.Page, oid: str):
    loading = ft.ProgressBar(visible=False)
    error_text = ft.Text("", color=ft.Colors.RED)
    status_text = ft.Text(size=20, weight=ft.FontWeight.BOLD)
    timeline_area = ft.Column(spacing=4)
    items_area = ft.Column(spacing=4)
    info_area = ft.Column(spacing=4)
    review_area = ft.Column(spacing=4)

    MAP_SIZE = 256
    _map_img = None
    _last_map_update = 0.0
    map_display = ft.Container(
        content=ft.Container(
            content=ft.Icon(ft.Icons.MAP, size=48, color=ft.Colors.GREY),
            height=MAP_SIZE, alignment="center",
        ),
        border_radius=12,
    )
    ws_status = ft.Text("", size=12, color=ft.Colors.GREY)
    state = {"status": None}

    async def load():
        loading.visible = True
        page.update()
        try:
            o = await api.get_order(oid)
            state["status"] = o.get("status")
            t = await api.get_order_tracking(oid)
            _render_order(o, t)
        except Exception as ex:
            error_text.value = str(ex)
        finally:
            loading.visible = False
            page.update()

    async def status_poll():
        while page.route == f"/order/{oid}":
            await asyncio.sleep(15)
            if page.route != f"/order/{oid}":
                break
            try:
                fresh = await api.get_order(oid)
            except Exception:
                continue
            if fresh.get("status") != state["status"]:
                await load()

    async def connect():
        try:
            o = await api.get_order(oid)
            _connect_ws(o)
        except Exception:
            pass

    def _set_map(lat: float, lng: float):
        nonlocal _map_img
        if _map_img is None:
            _map_ref, _map_img, _ = map_image(lat, lng, size=MAP_SIZE)
            map_display.content = _map_ref
        update_map(_map_img, None, lat, lng)

    def _render_tracking(t: dict):
        timeline_area.controls.clear()
        if t.get("status") == "cancelled":
            timeline_area.controls.append(
                ft.Text("Este pedido fue cancelado", color=ft.Colors.RED, weight=ft.FontWeight.BOLD)
            )
            return

        if t.get("eta_min"):
            timeline_area.controls.append(ft.Container(
                ft.Text(
                    f"Llegada estimada: ~{t['eta_min']} min"
                    + (f" · {t['distance_km']} km" if t.get("distance_km") is not None else ""),
                    size=12, color=ft.Colors.BLUE,
                ),
                padding=8, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH, border_radius=8,
            ))

        for step in t.get("timeline", []):
            completed = step.get("completed", False)
            subtitle = ""
            if step.get("at"):
                subtitle = step["at"][:16].replace("T", " ")
            timeline_area.controls.append(ft.Row([
                ft.Icon(
                    ft.Icons.CHECK_CIRCLE if completed else ft.Icons.RADIO_BUTTON_UNCHECKED,
                    size=16,
                    color=ft.Colors.GREEN if completed else ft.Colors.GREY,
                ),
                ft.Column([
                    ft.Text(step["label"], size=13, weight=ft.FontWeight.BOLD if completed else None,
                            color=ft.Colors.ON_SURFACE if completed else ft.Colors.GREY),
                    *([ft.Text(subtitle, size=10, color=ft.Colors.GREY)] if subtitle else []),
                ], spacing=0),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.START))

    def _render_initial_map(t: dict):
        point = t.get("courier") or t.get("destination") or t.get("restaurant")
        if point:
            _set_map(point["lat"], point["lng"])
        else:
            map_display.content = ft.Container(
                content=ft.Text("Ubicación no disponible", color=ft.Colors.GREY, text_align=ft.TextAlign.CENTER),
                height=MAP_SIZE, alignment="center",
            )

    def _render_order(o: dict, t: dict | None = None):
        status_text.value = STATUS_LABELS.get(o["status"], o["status"])
        status_text.color = STATUS_COLORS.get(o["status"], ft.Colors.GREY)
        if t:
            _render_tracking(t)
            _render_initial_map(t)
        items_area.controls.clear()
        for item in o.get("items", []):
            items_area.controls.append(ft.Row([
                ft.Text(item.get("name", "Artículo"), expand=True),
                ft.Text(f"x{item['quantity']}"),
                ft.Text(f"${float(item['subtotal']):.2f}"),
            ]))
        info_area.controls.clear()
        if o.get("fulfillment_type") == "pickup":
            info_area.controls.append(ft.Text(f"Recoger en: {o['delivery_address']}", size=13, color=ft.Colors.BLUE))
        else:
            info_area.controls.append(ft.Text(f"Dirección: {o['delivery_address']}", size=13))
        info_area.controls.append(ft.Text(f"Subtotal: ${float(o['subtotal']):.2f}"))
        info_area.controls.append(ft.Text(f"Envío: ${float(o['delivery_fee']):.2f}"))
        info_area.controls.append(ft.Text(f"Comisión por uso de la plataforma: ${float(o.get('flat_usage_fee') or 0):.2f}", size=13))
        if o.get("loyalty_discount") and float(o["loyalty_discount"]) > 0:
            info_area.controls.append(ft.Text(f"Puntos: -${float(o['loyalty_discount']):.2f} ({o.get('points_redeemed', 0)} pts)", size=13, color=ft.Colors.BLUE))
        info_area.controls.append(ft.Text(f"Total: ${float(o['total']):.2f}", weight=ft.FontWeight.BOLD))
        if o.get("tip_amount") and float(o["tip_amount"]) > 0:
            info_area.controls.append(ft.Text(f"Propina: ${float(o['tip_amount']):.2f}", size=13, color=ft.Colors.GREEN))
        if o.get("estimated_delivery_min"):
            info_area.controls.append(ft.Text(f"Tiempo estimado original: ~{o['estimated_delivery_min']} min", size=13, color=ft.Colors.BLUE))
        if o.get("scheduled_for"):
            info_area.controls.append(ft.Text(f"Programado para: {o['scheduled_for']}", size=13, color=ft.Colors.BLUE))

        async def repeat_order(e):
            from mobile.screens.restaurant_detail import cart
            cart.clear()
            for item in o.get("items", []):
                option_ids = [str(opt["option_id"]) for opt in item.get("options", []) if opt.get("option_id")]
                cart.append({
                    "menu_item_id": str(item["menu_item_id"]),
                    "quantity": item["quantity"],
                    "name": item["name"],
                    "price": float(item["unit_price"]),
                    "base_price": float(item["unit_price"]) - sum(float(opt.get("price_delta") or 0) for opt in item.get("options", [])),
                    "option_ids": option_ids,
                    "option_names": [f"{opt['group_name']}: {opt['name']}" for opt in item.get("options", [])],
                    "line_key": f"{item['menu_item_id']}|{','.join(sorted(option_ids))}",
                })
            await page.push_route(f"/cart/{o['restaurant_id']}")

        info_area.controls.append(ft.OutlinedButton(
            "Repetir pedido", icon=ft.Icons.REFRESH,
            on_click=lambda e: page.run_task(repeat_order, e),
        ))
        _build_review_ui(o)

    def _build_review_ui(o: dict):
        review_area.controls.clear()
        if o["status"] != "delivered":
            return
        page.run_task(_load_reviews, o)

    async def _load_reviews(o: dict):
        try:
            existing = await api.get_order_reviews(oid)
        except Exception:
            existing = []
        rated_restaurant = any(r.get("restaurant_id") for r in existing)
        rated_courier = any(r.get("delivery_person_id") for r in existing)
        review_area.controls.clear()
        review_area.controls.append(ft.Divider())
        review_area.controls.append(ft.Text("Califica tu pedido", size=16, weight=ft.FontWeight.BOLD))
        review_area.controls.append(_review_block(o, "restaurant", rated_restaurant))
        if o.get("delivery_person_id"):
            review_area.controls.append(_review_block(o, "courier", rated_courier))
        page.update()

    def _review_block(o: dict, target: str, already_rated: bool):
        label = "Restaurante" if target == "restaurant" else "Repartidor"
        if already_rated:
            return ft.Column([
                ft.Text(label, size=13, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Ya calificaste este restaurante." if target == "restaurant"
                    else "Ya calificaste a este repartidor.",
                    size=12, color=ft.Colors.GREEN,
                ),
            ], spacing=2)

        rating = ft.RadioGroup(content=ft.Row(
            [ft.Radio(value=str(i), label=str(i)) for i in range(1, 6)],
            wrap=True,
        ))
        comment = ft.TextField(label="Comentario (opcional)", multiline=True, min_lines=1)
        message = ft.Text("", size=11, color=ft.Colors.RED)
        button = ft.FilledButton("Enviar calificación")

        async def submit(e):
            if not rating.value:
                message.value = "Selecciona de 1 a 5 estrellas."
                page.update()
                return
            try:
                if target == "restaurant":
                    await api.create_review(
                        order_id=oid, rating=int(rating.value),
                        comment=comment.value or None,
                        restaurant_id=str(o["restaurant_id"]),
                    )
                else:
                    await api.create_review(
                        order_id=oid, rating=int(rating.value),
                        comment=comment.value or None,
                        delivery_person_id=str(o["delivery_person_id"]),
                    )
                snack(page, "Calificación enviada")
                await _load_reviews(o)
            except ApiError as ex:
                message.value = ex.detail
                page.update()

        button.on_click = lambda e: page.run_task(submit, e)
        return ft.Column([ft.Text(label, size=13, weight=ft.FontWeight.BOLD), rating, comment, button, message], spacing=4)

    def _connect_ws(o: dict):
        if o["status"] not in ACTIVE_STATUSES:
            ws_status.value = "Seguimiento finalizado"
            page.update()
            return
        if not api.token:
            ws_status.value = "Inicia sesión para ver el seguimiento en vivo"
            page.update()
            return

        ws_status.value = "Conectando..."
        page.update()

        async def ws_loop():
            nonlocal _last_map_update
            url = f"{api.ws_url}/orders/{oid}/track?token={quote(api.token)}"
            try:
                import websockets
                async with websockets.connect(url) as ws:
                    ws_status.value = "En vivo"
                    page.update()
                    while True:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        if data.get("type") == "tracking_state":
                            _render_tracking(data)
                            point = data.get("courier") or data.get("destination") or data.get("restaurant")
                            if point:
                                _set_map(point["lat"], point["lng"])
                            page.update()
                        elif data.get("type") == "status_update":
                            new_status = data["status"]
                            status_text.value = STATUS_LABELS.get(new_status, new_status)
                            status_text.color = STATUS_COLORS.get(new_status, ft.Colors.GREY)
                            snack(page, f"Estado actualizado: {STATUS_LABELS.get(new_status, new_status)}", ft.Colors.BLUE)
                            await load()
                        elif data.get("type") == "location_update":
                            now = time.monotonic()
                            # El mapa estático se re-renderiza como máximo cada 4 s
                            # para no saturar el servidor ni el CDN de tiles.
                            if now - _last_map_update >= 4:
                                _last_map_update = now
                                _set_map(data["lat"], data["lng"])
                                ws_status.value = f"En vivo - {data.get('speed_kmh', '?')} km/h"
                                page.update()
            except Exception as ex:
                ws_status.value = f"Desconectado: {ex}"
                page.update()

        page.run_task(ws_loop)

    page.run_task(load)
    page.run_task(connect)
    page.run_task(status_poll)

    appbar = ft.AppBar(bgcolor="#1B2F6B", color=ft.Colors.WHITE, 
        leading=ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda _: page.run_task(page.push_route, "/orders")),
        title=ft.Text(f"Pedido #{oid[:8]}"),
    )

    return ft.View(
        route=f"/order/{oid}",
        controls=[
            appbar,
            ft.SafeArea(ft.Column([
                error_text, loading,
                status_text,
                timeline_area,
                map_display, ws_status,
                ft.Divider(),
                ft.Text("Artículos", size=16, weight=ft.FontWeight.BOLD),
                items_area,
                ft.Divider(),
                info_area,
                review_area,
            ], scroll=ft.ScrollMode.AUTO, expand=True))
        ]
    )
