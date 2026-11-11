import re

import flet as ft
from mobile.api import api, ApiError
from mobile.location_service import compose_address, current_position, pick_colonia, reverse_address
from mobile.screens.restaurant_detail import cart
from mobile.utils import snack
from mobile.map_widget import map_image, update_map


_COORDS = [20.644, -100.993]


def cart_view(page: ft.Page, rid: str):
    if not cart:
        return ft.View(
            route=f"/cart/{rid}",
            controls=[
                ft.AppBar(title=ft.Text("Carrito")),
                ft.SafeArea(ft.Column([
                    ft.Container(height=60),
                    ft.Text("Carrito vacío", size=20, text_align=ft.TextAlign.CENTER),
                    ft.TextButton("Volver al menú", on_click=lambda _: page.run_task(page.push_route, f"/restaurant/{rid}")),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)),
            ]
        )

    total = ft.Text("$0.00", size=24, weight=ft.FontWeight.BOLD)
    estimate_text = ft.Text("", size=14, color=ft.Colors.GREY)
    items_list = ft.ListView(spacing=6, padding=10, expand=True)
    address = ft.TextField(label="Calle y número", multiline=False)
    _cp = ft.TextField(label="C.P.", width=118, max_length=5, keyboard_type=ft.KeyboardType.NUMBER)
    _colonia = ft.Dropdown(label="Colonia", expand=True, options=[], text_size=13)
    notes = ft.TextField(label="Notas (opcional)", multiline=True, min_lines=1)
    error_text = ft.Text("", color=ft.Colors.RED)
    loading = ft.ProgressBar(visible=False)
    coupon_input = ft.TextField(label="Cupón de descuento", hint_text="EJ: BIENVENIDO10")
    coupon_status = ft.Text("", size=12)
    _applied_coupon = [None]
    _detecting = ft.Text("", size=12, color=ft.Colors.GREY)
    _user_lat = ft.TextField(label="Latitud", value=str(_COORDS[0]), visible=False)
    _user_lng = ft.TextField(label="Longitud", value=str(_COORDS[1]), visible=False)
    _loc_btn = ft.FilledTonalButton("Usar mi ubicación")
    fee_subtotal = ft.Text("", size=13)
    fee_delivery = ft.Text("", size=13)
    fee_flat = ft.Text("", size=13)
    fee_discount = ft.Text("", size=13, color=ft.Colors.GREEN)
    fee_tip = ft.Text("", size=13, color=ft.Colors.ORANGE)
    fee_points = ft.Text("", size=13, color=ft.Colors.BLUE)
    points_balance = ft.Text("", size=12, color=ft.Colors.GREY)
    points_input = ft.TextField(
        label="Puntos a canjear", width=160, text_size=13,
        keyboard_type=ft.KeyboardType.NUMBER,
    )
    _loyalty_points = [0]
    _loyalty_visible = [True]
    _loyalty_value = [1.0]
    loyalty_box = ft.Container(visible=False)
    _payment_method = ["cash"]
    _tip_amount = [0.0]
    _fulfillment = ["delivery"]
    _restaurant = [{}]
    _bank_details = {}
    _bank_info = ft.Column([], spacing=4, visible=False)
    _geo_state = {"address": ""}
    _geocode_msg = ft.Text("", size=11, color=ft.Colors.GREY)
    _geocode_btn = ft.FilledTonalButton("Buscar dirección")

    _map_size = 280
    _map_zoom = 16
    _map_display, _map_img, _ = map_image(_COORDS[0], _COORDS[1], zoom=_map_zoom, size=_map_size)

    def _update_map(lat: float, lng: float):
        _user_lat.value = str(lat)
        _user_lng.value = str(lng)
        _COORDS[0] = lat
        _COORDS[1] = lng
        update_map(_map_img, None, lat, lng, zoom=_map_zoom, size=_map_size)
        page.update()

    def _on_map_tap(e):
        import math
        pos = getattr(e, "local_position", None)
        if pos is None:
            return
        lat, lng = _COORDS[0], _COORDS[1]
        meters_per_pixel = 156543.03392 * math.cos(math.radians(lat)) / (2 ** _map_zoom)
        dx = pos.x - _map_size / 2
        dy = pos.y - _map_size / 2
        new_lat = lat - (dy * meters_per_pixel) / 111320.0
        new_lng = lng + (dx * meters_per_pixel) / (
            111320.0 * max(math.cos(math.radians(lat)), 0.1)
        )
        _update_map(new_lat, new_lng)
        _detecting.value = "Pin ajustado en el mapa. Se usará esta ubicación para el envío."
        _detecting.color = ft.Colors.GREEN

    _map_gesture = ft.GestureDetector(content=_map_display, on_tap_down=_on_map_tap)

    _update_map(_COORDS[0], _COORDS[1])

    def _set_colonia(name: str):
        if not name:
            return
        names = [o.key for o in _colonia.options]
        chosen = pick_colonia(names, name) or name
        if chosen not in names:
            _colonia.options.append(ft.dropdown.Option(key=chosen, text=chosen))
        _colonia.value = chosen

    async def _load_cp_colonias(cp: str, selected: str = ""):
        if len(cp or "") != 5:
            return
        try:
            data = await api.get_colonias(cp)
        except Exception:
            return
        names = [c.get("nombre") for c in (data.get("colonias") or []) if c.get("nombre")]
        _colonia.options = [ft.dropdown.Option(key=n, text=n) for n in names]
        if selected:
            _set_colonia(selected)
        elif len(names) == 1:
            _colonia.value = names[0]
        page.update()

    def _on_cp_change(e):
        cp = re.sub(r"\D", "", _cp.value or "")[:5]
        if cp != (_cp.value or ""):
            _cp.value = cp
        if len(cp) == 5:
            page.run_task(_load_cp_colonias, cp)
        page.update()

    _cp.on_change = _on_cp_change

    async def _init_location():
        try:
            addrs = await api.list_addresses()
            if addrs:
                a = addrs[0]
                lat = a.get("location", {}).get("lat", _COORDS[0])
                lng = a.get("location", {}).get("lng", _COORDS[1])
                _COORDS[0] = lat
                _COORDS[1] = lng
                _user_lat.value = str(lat)
                _user_lng.value = str(lng)
                _update_map(lat, lng)
                address.value = a.get("address") or ""
                _geo_state["address"] = address.value
                _detecting.value = f"Usando dirección guardada: {a['name']}"
                page.update()
                return

            pos = await current_position()
            lat, lng = pos["lat"], pos["lng"]
            _COORDS[0] = lat
            _COORDS[1] = lng
            _update_map(lat, lng)
            found = await reverse_address(lat, lng)
            if found["street"]:
                address.value = found["street"]
            if found["cp"]:
                _cp.value = found["cp"]
                await _load_cp_colonias(found["cp"], found["colonia"])
            elif found["colonia"]:
                _set_colonia(found["colonia"])
            full = compose_address(address.value, _colonia.value or "", _cp.value or "")
            _geo_state["address"] = full
            _detecting.value = (
                f"{pos['source']}: {full}. Corrige la calle o ajusta la ubicación."
                if full else f"{pos['source']} aplicada. Escribe la dirección."
            )
            page.update()
        except Exception:
            pass

    page.run_task(_init_location)

    def rebuild_items():
        items_list.controls.clear()
        subtotal = 0.0
        for ci in cart:
            subtotal += ci['price'] * ci['quantity']
            items_list.controls.append(ft.Container(
                content=ft.Row([
                    ft.Column([
                        ft.Text(ci.get("name", ci["menu_item_id"][:8]), expand=True, size=15),
                        *([ft.Text(" · ".join(ci.get("option_names") or []), size=11, color=ft.Colors.GREY)] if ci.get("option_names") else []),
                    ], expand=True, spacing=0),
                    ft.Text(f"x{ci['quantity']}", size=14),
                    ft.Text(f"${ci['price'] * ci['quantity']:.2f}", size=14),
                ]),
                padding=6,
            ))
        total.value = f"${subtotal:.2f}"

    rebuild_items()

    async def _detect_location(e):
        _detecting.value = "Detectando ubicación..."
        _loc_btn.disabled = True
        page.update()
        try:
            pos = await current_position()
            lat, lng = pos["lat"], pos["lng"]
            _update_map(lat, lng)
            found = await reverse_address(lat, lng)
            if found["street"]:
                address.value = found["street"]
            if found["cp"]:
                _cp.value = found["cp"]
                await _load_cp_colonias(found["cp"], found["colonia"])
            elif found["colonia"]:
                _set_colonia(found["colonia"])
            full = compose_address(address.value, _colonia.value or "", _cp.value or "")
            if full:
                _geo_state["address"] = full
                _detecting.value = f"{pos['source']}: {full}. Corrige la calle o ajusta la ubicación."
                _detecting.color = ft.Colors.GREEN
            else:
                _detecting.value = f"{pos['source']} aplicada. Escribe calle, colonia y C.P. manualmente."
                _detecting.color = ft.Colors.ORANGE
            await load_price_estimate()
            await load_estimate()
        except ApiError:
            _detecting.value = "Servicio no disponible, escribe tu dirección manualmente"
        except Exception:
            _detecting.value = "Error al detectar ubicación"
        finally:
            _loc_btn.disabled = False
            page.update()

    _loc_btn.on_click = lambda e: page.run_task(_detect_location, e)

    async def _geocode_from_address(e=None) -> bool:
        street = (address.value or "").strip()
        cp = re.sub(r"\D", "", _cp.value or "")[:5]
        colonia = (_colonia.value or "").strip()
        full = compose_address(street, colonia, cp)
        if len(street) < 3:
            _geocode_msg.value = "Escribe calle y número."
            _geocode_msg.color = ft.Colors.RED
            page.update()
            return False
        _geocode_btn.disabled = True
        _geocode_msg.value = "Buscando dirección..."
        _geocode_msg.color = ft.Colors.GREY
        page.update()
        try:
            results = []
            if cp and colonia:
                results = await api.geocode_structured(street, colonia, cp)
            if not results:
                query = (
                    compose_address(street, colonia, cp)
                    + ", Santa Cruz de Juventino Rosas, Guanajuato, México"
                )
                results = await api.geocode_address(query)
            if not results:
                raise ValueError("No se encontró la dirección")
            r = results[0]
            lat, lng = float(r["lat"]), float(r["lng"])
            note = f"Ubicación: {r.get('display_name', '')}"

            if cp and r.get("postcode") and str(r["postcode"]) != cp:
                # No confiar en una calle de otra colonia: usar el centro del C.P.
                try:
                    cp_data = await api.get_colonias(cp)
                    if cp_data.get("lat") is not None:
                        lat, lng = float(cp_data["lat"]), float(cp_data["lng"])
                        note = (
                            f"No encontramos esa calle exacta en el C.P. {cp}; "
                            "se usará el centro de ese C.P. para el envío."
                        )
                except Exception:
                    pass

            _update_map(lat, lng)
            _geo_state["address"] = full
            _geocode_msg.value = note
            _geocode_msg.color = ft.Colors.ORANGE if "No encontramos" in note else ft.Colors.GREEN
            await load_price_estimate()
            await load_estimate()
            return True
        except Exception as ex:
            _geocode_msg.value = f"No se pudo ubicar: {ex}"
            _geocode_msg.color = ft.Colors.RED
            return False
        finally:
            _geocode_btn.disabled = False
            page.update()

    _geocode_btn.on_click = lambda e: page.run_task(_geocode_from_address, e)

    _update_map(_COORDS[0], _COORDS[1])

    async def load_estimate():
        items_data = [{"menu_item_id": ci["menu_item_id"], "quantity": ci["quantity"], "option_ids": ci.get("option_ids", [])} for ci in cart]
        try:
            res = await api.estimate_time(rid, items_data, _COORDS[0], _COORDS[1])
            mins = res.get("estimated_delivery_min", 0)
            estimate_text.value = f"🕐 Tiempo estimado: ~{mins} min"
            page.update()
        except ApiError:
            pass

    page.run_task(load_estimate)

    _points_to_redeem = [0]

    async def load_loyalty():
        try:
            prof = await api.get_profile()
        except Exception:
            return
        _loyalty_points[0] = int(prof.get("loyalty_points") or 0)
        points_balance.value = f"Tienes {_loyalty_points[0]} puntos. Cada punto descuenta ${_loyalty_value[0]:.2f}."
        loyalty_box.visible = _loyalty_visible[0] and _loyalty_points[0] > 0
        page.update()

    async def load_price_estimate():
        items_data = [{"menu_item_id": ci["menu_item_id"], "quantity": ci["quantity"], "option_ids": ci.get("option_ids", [])} for ci in cart]
        try:
            res = await api.estimate_price(
                rid, items_data,
                None if _fulfillment[0] == "pickup" else _COORDS[0],
                None if _fulfillment[0] == "pickup" else _COORDS[1],
                _applied_coupon[0], _tip_amount[0], _points_to_redeem[0], _fulfillment[0],
            )
            fee_subtotal.value = f"Subtotal: ${res.get('subtotal', '0.00')}"
            fee_delivery.value = f"Envío: ${res.get('delivery_fee', '0.00')}"
            fee_flat.value = f"Comisión por uso de plataforma: ${res.get('flat_usage_fee', '0.00')}"
            fee_tip.value = f"Propina: ${res.get('tip_amount', '0.00')}" if _tip_amount[0] > 0 else ""
            disc = res.get('discount', '0.00')
            fee_discount.value = f"Descuento: -${disc}" if disc != '0.00' else ""
            used = int(res.get('points_redeemed') or 0)
            loyalty_discount = float(res.get('loyalty_discount') or 0)
            _points_to_redeem[0] = used
            fee_points.value = (
                f"Puntos: -${loyalty_discount:.2f} ({used} pts)"
                if loyalty_discount > 0 else ""
            )
            if points_input.value != str(used):
                points_input.value = str(used) if used else ""
            total.value = f"${res.get('total', '0.00')}"
            page.update()
        except ApiError:
            pass

    page.run_task(load_price_estimate)

    _tip_btns = []
    for _amount, _label in [(0, "Sin propina"), (10, "$10"), (20, "$20"), (30, "$30")]:
        _tip_btns.append(ft.Container(
            content=ft.Text(_label, size=12),
            padding=8, border_radius=8, ink=True, data=_amount,
        ))
    _tip_custom = ft.TextField(
        hint_text="Otra", width=80, text_size=12,
        keyboard_type=ft.KeyboardType.NUMBER,
    )

    def _select_tip(value):
        try:
            _tip_amount[0] = max(0.0, min(1000.0, float(value or 0)))
        except (TypeError, ValueError):
            _tip_amount[0] = 0.0
        for btn in _tip_btns:
            btn.bgcolor = ft.Colors.GREEN_100 if float(btn.data) == _tip_amount[0] else None
        page.run_task(load_price_estimate)
        page.update()

    for _btn in _tip_btns:
        _btn.on_click = lambda e, value=_btn.data: _select_tip(value)
    _tip_custom.on_change = lambda e: _select_tip(e.control.value)
    _select_tip(0)

    def _on_points_change(e):
        try:
            value = int(float(points_input.value or 0))
        except (TypeError, ValueError):
            value = 0
        _points_to_redeem[0] = max(0, min(_loyalty_points[0], value))
        page.run_task(load_price_estimate)

    points_input.on_change = _on_points_change
    loyalty_box.content = ft.Column([
        ft.Text("Puntos de lealtad", size=15, weight=ft.FontWeight.BOLD),
        ft.Row([points_input, ft.TextButton("Usar todos", on_click=lambda e: (points_input.__setattr__("value", str(_loyalty_points[0])), _on_points_change(e), page.update()))]),
        points_balance,
    ], spacing=4)
    page.run_task(load_loyalty)

    async def apply_coupon(e):
        code = coupon_input.value.strip().upper()
        if not code:
            return
        try:
            subtotal_val = sum(ci["price"] * ci["quantity"] for ci in cart)
            res = await api.validate_coupon(code, float(subtotal_val), rid)
            if res.get("valid"):
                coupon_status.value = res["message"]
                coupon_status.color = ft.Colors.GREEN
                coupon_input.disabled = True
                _applied_coupon[0] = code
            else:
                coupon_status.value = res.get("message", "Cupón inválido")
                coupon_status.color = ft.Colors.RED
                _applied_coupon[0] = None
            page.update()
        except ApiError as ex:
            coupon_status.value = ex.detail
            coupon_status.color = ft.Colors.RED
            page.update()

    async def _load_bank_details():
        try:
            _bank_details.clear()
            _bank_details.update(await api.get_bank_details())
        except Exception:
            _bank_details["bank_name"] = "Banco"
            _bank_details["account_holder"] = "TuPedidoJR"
            _bank_details["clabe"] = "000000000000000000"

    page.run_task(_load_bank_details)

    _pay_btn_cash = ft.Container(
        content=ft.Column([
            ft.Icon(ft.Icons.MONEY, size=24),
            ft.Text("Efectivo", size=12),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
        padding=10, border_radius=8, ink=True,
        bgcolor=ft.Colors.GREEN_100, data="cash", key="pay_cash",
    )
    _pay_btn_transfer = ft.Container(
        content=ft.Column([
            ft.Icon(ft.Icons.ACCOUNT_BALANCE, size=24),
            ft.Text("Transferencia", size=12),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
        padding=10, border_radius=8, ink=True,
        data="transfer", key="pay_transfer",
    )
    _pay_btn_mp = ft.Container(
        content=ft.Column([
            ft.Icon(ft.Icons.LOCK, size=24, color=ft.Colors.GREY),
            ft.Text("Mercado Pago", size=12, color=ft.Colors.GREY),
            ft.Text("Próximamente", size=9, color=ft.Colors.GREY),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=2),
        padding=10, border_radius=8,
        bgcolor=ft.Colors.GREY_100,
    )
    # Transferencia habilitada; Mercado Pago deshabilitado.
    _payment_method_btns = [_pay_btn_cash, _pay_btn_transfer]

    async def _load_payment_config():
        try:
            config = await api.payment_config()
        except Exception:
            return
        _loyalty_visible[0] = bool(config.get("loyalty_visible", True)) and bool(config.get("loyalty_enabled", True))
        try:
            _loyalty_value[0] = float(config.get("loyalty_value_per_point") or 1)
        except (TypeError, ValueError):
            _loyalty_value[0] = 1.0
        if not _loyalty_visible[0]:
            loyalty_box.visible = False
        buttons = [_pay_btn_cash]
        if config.get("transfer_enabled", True):
            buttons.append(_pay_btn_transfer)
        _payment_method_btns[:] = buttons
        payment_row.controls = list(buttons)
        if _payment_method[0] not in [b.data for b in buttons]:
            _select_payment("cash")
        page.update()

    def _select_payment(method: str):
        _payment_method[0] = method
        _bank_info.visible = method == "transfer"
        if method == "transfer":
            has_data = bool(_bank_details.get("bank_name") or _bank_details.get("clabe") or _bank_details.get("account_holder"))
            if has_data:
                _bank_info.controls = [
                    ft.Text("Transferencia a TuPedidoJR (plataforma):", size=13, weight=ft.FontWeight.BOLD),
                    ft.Text(f"Banco: {_bank_details.get('bank_name', '')}", size=12),
                    ft.Text(f"Titular: {_bank_details.get('account_holder', '')}", size=12),
                    ft.Text(f"CLABE: {_bank_details.get('clabe', '')}", size=12, selectable=True),
                ]
                if _bank_details.get("card"):
                    _bank_info.controls.append(ft.Text(f"Tarjeta: {_bank_details['card']}", size=12, selectable=True))
                _bank_info.controls.append(ft.Text(
                    "El dinero entra a la plataforma. El repartidor no te cobrará en efectivo por este pedido; su pago lo cubre TuPedidoJR.",
                    size=11, color=ft.Colors.GREY,
                ))
            else:
                _bank_info.controls = [
                    ft.Text("La plataforma aún no configuró la cuenta bancaria.", size=12, color=ft.Colors.RED),
                ]
        for c in _payment_method_btns:
            c.bgcolor = ft.Colors.GREEN_100 if c.data == method else None
        for c in _payment_method_btns:
            if c.data:
                c.on_click = lambda e, m=c.data: _select_payment(m)
        page.update()

    _select_payment("cash")

    async def place_order(e):
        pickup = _fulfillment[0] == "pickup"
        street = (address.value or "").strip()
        cp = re.sub(r"\D", "", _cp.value or "")[:5]
        colonia = (_colonia.value or "").strip()
        full_address = compose_address(street, colonia, cp)
        if not pickup and len(street) < 3:
            error_text.value = "Escribe calle y número para la entrega"
            page.update()
            return
        if not pickup and _geo_state["address"] != full_address:
            ok = await _geocode_from_address()
            if not ok:
                error_text.value = "No se pudo ubicar la dirección. Revisa calle, colonia y C.P."
                page.update()
                return
        error_text.value = ""
        loading.visible = True
        page.update()
        try:
            items_data = [{"menu_item_id": ci["menu_item_id"], "quantity": ci["quantity"], "option_ids": ci.get("option_ids", [])} for ci in cart]
            pm = _payment_method[0]
            result = await api.create_order(
                restaurant_id=rid,
                items=items_data,
                delivery_address=None if pickup else full_address,
                lat=None if pickup else float(_user_lat.value),
                lng=None if pickup else float(_user_lng.value),
                notes=notes.value or None,
                coupon_code=_applied_coupon[0],
                payment_method=pm,
                tip_amount=0 if pickup else _tip_amount[0],
                points_to_redeem=_points_to_redeem[0],
                fulfillment_type="pickup" if pickup else "delivery",
            )
            cart.clear()
            try:
                await api.save_cart_snapshot([], None)
            except Exception:
                pass
            snack(page, f"Pedido #{result['id'][:8]} creado")
            if pm == "cash":
                await page.push_route(f"/order/{result['id']}")
            elif pm == "transfer":
                await page.push_route(f"/order/{result['id']}")
            else:
                await page.push_route(f"/payment/{result['id']}")
        except ApiError as ex:
            error_text.value = f"Error del servidor: {ex.detail}"
        except Exception as ex:
            error_text.value = f"Error inesperado: {ex}"
        finally:
            loading.visible = False
            page.update()

    def go_back(e=None):
        page.run_task(page.push_route, f"/restaurant/{rid}")

    appbar = ft.AppBar(
        title=ft.Image(src="logo.png", height=28),
        leading=ft.IconButton(ft.Icons.ARROW_BACK, on_click=go_back),
        center_title=True,
        toolbar_height=48,
    )

    pickup_switch = ft.Switch(label="Recoger en el restaurante", value=False, visible=False)
    pickup_info = ft.Text("", size=12, color=ft.Colors.GREY, visible=False)
    pickup_box = ft.Container(
        content=ft.Column([
            pickup_switch,
            pickup_info,
            ft.Text("No se cobra envío ni propina. Te avisaremos cuando esté listo.", size=11, color=ft.Colors.GREY),
        ], spacing=4),
        padding=10, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH, border_radius=10, visible=False,
    )

    address_row = ft.Column([
        ft.Row([_cp, _colonia], spacing=6),
        address,
        ft.Row([
            _geocode_btn,
            ft.IconButton(ft.Icons.MY_LOCATION, tooltip="Detectar ubicación", on_click=lambda e: page.run_task(_detect_location, e)),
            _loc_btn,
        ], spacing=4, alignment=ft.MainAxisAlignment.START, wrap=True),
        _geocode_msg,
    ], spacing=4)

    coupon_row = ft.Column([
        ft.Row([coupon_input, ft.FilledButton("Aplicar", on_click=apply_coupon)], spacing=6),
        coupon_status,
    ], spacing=4)

    PAD = ft.Padding(left=10, right=10, top=0, bottom=0)

    payment_row = ft.Row(_payment_method_btns, spacing=8, alignment=ft.MainAxisAlignment.CENTER)

    address_container = ft.Container(address_row, padding=PAD)
    coords_row = ft.Row([_user_lat, _user_lng], spacing=4)
    map_container = ft.Container(
        ft.Column([_map_gesture, _detecting], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4),
        padding=PAD,
    )
    tip_container = ft.Container(ft.Column([
        ft.Text("Propina para el repartidor", size=15, weight=ft.FontWeight.BOLD),
        ft.Row(_tip_btns + [_tip_custom], spacing=6, wrap=True),
        ft.Text("La propina es 100 % para el repartidor.", size=11, color=ft.Colors.GREY),
    ], spacing=4), padding=PAD)

    def _apply_fulfillment(pickup: bool):
        _fulfillment[0] = "pickup" if pickup else "delivery"
        address_container.visible = not pickup
        coords_row.visible = not pickup
        map_container.visible = not pickup
        tip_container.visible = not pickup
        if pickup:
            _tip_amount[0] = 0.0
            _tip_custom.value = ""
            for btn in _tip_btns:
                btn.bgcolor = ft.Colors.GREEN_100 if float(btn.data) == 0 else None
        page.run_task(load_price_estimate)
        page.update()

    pickup_switch.on_change = lambda e: _apply_fulfillment(bool(e.control.value))

    async def load_restaurant_info():
        try:
            r = await api.get_restaurant(rid)
        except Exception:
            return
        _restaurant[0] = r
        if r.get("pickup_enabled"):
            pickup_box.visible = True
            pickup_switch.visible = True
            pickup_info.visible = True
            pickup_info.value = f"{r.get('name', '')} — {r.get('address', '')}"
            page.update()

    page.run_task(load_restaurant_info)

    scrollable = ft.Column([
        items_list,
        ft.Divider(height=1),
        ft.Container(ft.Column([total, estimate_text], spacing=2), padding=PAD),
        ft.Container(ft.Column([fee_subtotal, fee_delivery, fee_flat, fee_tip, fee_points, fee_discount], spacing=2), padding=PAD),
        ft.Divider(height=1),
        ft.Container(pickup_box, padding=PAD),
        address_container,
        coords_row,
        map_container,
        ft.Container(notes, padding=PAD),
        ft.Container(coupon_row, padding=PAD),
        ft.Container(loyalty_box, padding=PAD),
        ft.Divider(height=1),
        ft.Container(ft.Column([
            ft.Text("Método de pago", size=15, weight=ft.FontWeight.BOLD),
            payment_row,
            _bank_info,
        ], spacing=6), padding=PAD),
        tip_container,
        ft.Container(ft.Column([error_text, loading], spacing=4), padding=PAD),
    ], scroll=ft.ScrollMode.AUTO, expand=True)

    bottom = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.FilledButton("Volver al menú", on_click=go_back, expand=True),
                ft.FilledButton("Confirmar pedido", on_click=place_order, expand=True),
            ], spacing=10),
        ]),
        padding=15, bgcolor=ft.Colors.SURFACE_CONTAINER,
    )

    page.run_task(_load_payment_config)

    return ft.View(
        route=f"/cart/{rid}",
        controls=[
            appbar,
            ft.Column([
                scrollable,
                bottom,
            ], spacing=0, expand=True),
        ]
    )
