import flet as ft
from mobile.api import api, ApiError
from mobile.cart_sync import sync_cart
from mobile.utils import close_dlg, open_dlg, snack, pick_image_file, dialog_width


cart: list[dict] = []


def restaurant_detail_view(page: ft.Page, rid: str):
    loading = ft.ProgressBar(visible=False)
    error_text = ft.Text("", color=ft.Colors.RED)
    menu_area = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)
    resto_name = ft.Text(size=22, weight=ft.FontWeight.BOLD)
    resto_cuisine = ft.Text(size=13, color=ft.Colors.BLUE)
    resto_status = ft.Text(size=13, color=ft.Colors.GREEN)
    commission_note = ft.Text("", size=11, color=ft.Colors.BLUE, visible=False)
    resto_logo = ft.Image(src="", width=100, height=100, border_radius=12, fit=ft.BoxFit.COVER)
    upload_status = ft.Text("", size=12, color=ft.Colors.GREEN)

    async def _upload_logo(e):
        path = pick_image_file()
        if not path:
            return
        try:
            await api.upload_restaurant_logo(rid, path)
            upload_status.value = "Logo actualizado"
            upload_status.color = ft.Colors.GREEN
            await load()
        except ApiError as ex:
            upload_status.value = f"Error: {ex.detail}"
            upload_status.color = ft.Colors.RED
        page.update()

    async def load():
        nonlocal loading, error_text, resto_name, menu_area, upload_btn, upload_status, owner_panel, leading_btn, orders_btn, earnings_btn, cart_btn, page
        loading.visible = True
        error_text.value = ""
        page.update()
        try:
            r = await api.get_restaurant(rid)
            resto_name.value = r["name"]
            resto_cuisine.value = " · ".join(filter(None, [
                r.get("cuisine") or "",
                "Entrega propia" if r.get("delivery_mode") == "own" else "",
                "Recoger en restaurante" if r.get("pickup_enabled") else "",
            ]))
            is_open_now = r.get("is_open_now")
            if is_open_now is False:
                resto_status.value = "Cerrado · " + (r.get("open_message") or "")
                resto_status.color = ft.Colors.RED
            else:
                resto_status.value = "Abierto · " + (r.get("open_message") or "")
                resto_status.color = ft.Colors.GREEN
            if r.get("logo_url"):
                resto_logo.src = f"{api.api_url}{r['logo_url']}"
                resto_logo.visible = True
            else:
                resto_logo.visible = False

            commission_rate = float(r.get("effective_commission_percentage") or 0)
            role = r.get("viewer_role")
            is_staff = bool(role)
            is_owner = role in ("owner", "admin")
            can_manage = role in ("owner", "manager", "admin")
            upload_btn.visible = False
            owner_panel.visible = is_staff
            business_profile_btn.visible = can_manage
            add_cat_btn.visible = can_manage
            add_item_btn.visible = can_manage
            orders_btn.visible = is_staff
            earnings_btn.visible = can_manage
            team_btn.visible = is_owner
            profile_btn.visible = is_staff
            if can_manage:
                profile_btn.tooltip = "Perfil del negocio"
                profile_btn.on_click = lambda e: page.run_task(page.push_route, f"/restaurant-profile/{rid}")
            else:
                profile_btn.tooltip = "Mi perfil"
                profile_btn.on_click = lambda e: page.run_task(page.push_route, "/profile")
            cart_btn.visible = not is_staff
            leading_btn.icon = ft.Icons.ARROW_BACK
            leading_btn.on_click = (lambda e: page.run_task(page.push_route, "/restaurants"))
            leading_btn.tooltip = "Atrás"
            leading_btn.visible = not is_staff
            if commission_rate > 0:
                commission_note.visible = can_manage
                commission_note.value = (
                    f"Tus precios son la base. Al cliente se le suma {commission_rate:.1f}% de comisión de plataforma."
                    if can_manage else ""
                )

            menu_area.controls.clear()
            for cat in r.get("categories", []):
                menu_area.controls.append(ft.Text(cat["name"], size=16, weight=ft.FontWeight.BOLD))
                items = [i for i in r.get("menu", []) if i.get("category_id") == cat["id"]]
                for item in items:
                    menu_area.controls.append(_menu_item_card(page, item, rid, can_manage, commission_rate, is_staff))
            uncategorized = [i for i in r.get("menu", []) if not i.get("category_id")]
            if uncategorized:
                menu_area.controls.append(ft.Text("Otros", size=16, weight=ft.FontWeight.BOLD))
                for item in uncategorized:
                    menu_area.controls.append(_menu_item_card(page, item, rid, can_manage, commission_rate, is_staff))
        except ApiError as ex:
            error_text.value = ex.detail
        except Exception as ex:  # noqa: BLE001
            error_text.value = f"No se pudo cargar el restaurante: {ex}"
            print("Error cargando restaurante:", repr(ex), flush=True)
        finally:
            loading.visible = False
            page.update()

    page.run_task(load)

    upload_btn = ft.FilledTonalButton("Cambiar logo", icon=ft.Icons.UPLOAD_FILE, on_click=lambda e: page.run_task(_upload_logo, e), visible=False)
    leading_btn = ft.IconButton(ft.Icons.ARROW_BACK, on_click=lambda e: page.run_task(page.push_route, "/restaurants"))
    add_cat_btn = ft.OutlinedButton("+ Categoría", icon=ft.Icons.FOLDER, on_click=lambda e: page.run_task(_open_add_category, e), visible=False)
    add_item_btn = ft.FilledButton("+ Platillo", icon=ft.Icons.ADD, on_click=lambda e: page.run_task(_open_add_item, e), visible=False)
    orders_btn = ft.FilledTonalButton("Pedidos", icon=ft.Icons.RECEIPT_LONG, on_click=lambda e: page.run_task(page.push_route, f"/restaurant-orders/{rid}"), visible=False)
    earnings_btn = ft.FilledTonalButton("Ganancias", icon=ft.Icons.ATTACH_MONEY, on_click=lambda e: page.run_task(page.push_route, f"/restaurant-earnings/{rid}"), visible=False)
    team_btn = ft.FilledTonalButton("Equipo", icon=ft.Icons.PEOPLE, on_click=lambda e: page.run_task(page.push_route, f"/restaurant-team/{rid}"), visible=False)
    business_profile_btn = ft.FilledTonalButton("Perfil del negocio", icon=ft.Icons.STORE, on_click=lambda e: page.run_task(page.push_route, f"/restaurant-profile/{rid}"), visible=False)
    profile_btn = ft.IconButton(ft.Icons.PERSON, tooltip="Perfil del negocio", on_click=lambda e: page.run_task(page.push_route, f"/restaurant-profile/{rid}"), visible=False)
    cart_btn = ft.IconButton(ft.Icons.SHOPPING_CART, on_click=lambda e: page.run_task(page.push_route, f"/cart/{rid}"))

    cat_input = ft.TextField(label="Nombre de la categoría", autofocus=True)
    item_name = ft.TextField(label="Nombre del platillo")
    item_price = ft.TextField(label="Precio", keyboard_type=ft.KeyboardType.NUMBER)
    item_desc = ft.TextField(label="Descripción (opcional)", multiline=True)
    item_cat = ft.Dropdown(label="Categoría (opcional)")
    item_err = ft.Text("", color=ft.Colors.RED, size=12)

    async def _do_add_category(e):
        if not cat_input.value:
            return
        try:
            await api.create_menu_category(rid, cat_input.value)
            cat_input.value = ""
            await load()
        except ApiError as ex:
            snack(page, f"Error: {ex.detail}", ft.Colors.RED)
        page.pop_dialog()

    cat_dialog = ft.AlertDialog(
        title=ft.Text("Agregar categoría"),
        content=cat_input,
        actions=[
            ft.TextButton("Cancelar", on_click=lambda e: page.pop_dialog()),
            ft.FilledButton("Agregar", on_click=lambda e: page.run_task(_do_add_category, e)),
        ],
    )

    async def _open_add_category(e):
        cat_input.value = ""
        page.show_dialog(cat_dialog)

    async def _do_add_item(e):
        if not item_name.value or not item_price.value:
            snack(page, "Nombre y precio son obligatorios", ft.Colors.RED)
            return
        try:
            price = float(item_price.value)
            cat_id = item_cat.value if item_cat.value else None
            await api.create_menu_item(rid, item_name.value, price, cat_id, item_desc.value or None)
            item_name.value = ""
            item_price.value = ""
            item_desc.value = ""
            await load()
        except ValueError:
            snack(page, "Precio inválido", ft.Colors.RED)
        except ApiError as ex:
            snack(page, f"Error: {ex.detail}", ft.Colors.RED)
        page.pop_dialog()

    item_dialog = ft.AlertDialog(
        title=ft.Text("Agregar platillo"),
        content=ft.Column([item_name, item_price, item_desc, item_cat, item_err], tight=True, width=dialog_width(page)),
        actions=[
            ft.TextButton("Cancelar", on_click=lambda e: page.pop_dialog()),
            ft.FilledButton("Agregar", on_click=lambda e: page.run_task(_do_add_item, e)),
        ],
    )

    async def _open_add_item(e):
        item_name.value = ""
        item_price.value = ""
        item_desc.value = ""
        item_cat.value = None
        item_err.value = ""
        try:
            r = await api.get_restaurant(rid)
            cats = r.get("categories", [])
            item_cat.options = [ft.dropdown.Option(text=c["name"], key=c["id"]) for c in cats]
        except ApiError:
            pass
        page.show_dialog(item_dialog)

    owner_panel = ft.Container(
        content=ft.Column([
            ft.Text("Panel del restaurante", weight=ft.FontWeight.BOLD, size=14),
            ft.Row([
                business_profile_btn,
                add_cat_btn,
                add_item_btn,
            ], spacing=8, wrap=True),
            ft.Row([
                orders_btn,
                earnings_btn,
                team_btn,
            ], spacing=8, wrap=True),
        ], spacing=8),
        padding=ft.Padding(top=0, bottom=8, left=0, right=0),
        visible=False,
    )

    appbar = ft.AppBar(
        title=ft.Image(src="logo.png", height=28),
        leading=leading_btn,
        actions=[
            cart_btn,
            profile_btn,
        ],
        center_title=True,
        toolbar_height=48,
    )

    return ft.View(
        route=f"/restaurant/{rid}",
        controls=[
            appbar,
            ft.Column([
                resto_logo, resto_name, resto_cuisine, resto_status, error_text, upload_status, loading,
                commission_note,
                owner_panel,
                menu_area,
            ], expand=True),
        ]
    )


def _cart_line_key(item_id: str, option_ids=None) -> str:
    return f"{item_id}|{','.join(sorted(str(x) for x in (option_ids or [])))}"


def _open_item_customizer(page: ft.Page, item: dict, rid: str | None = None, commission_rate: float = 0):
    groups = item.get("option_groups") or []
    base_price = float(item["price"])
    choices: dict = {}
    price_text = ft.Text(f"${_customer_price(base_price, commission_rate):.2f}", size=16, weight=ft.FontWeight.BOLD)
    qty = ft.TextField(
        value="1", width=70, label="Cantidad", text_size=13,
        keyboard_type=ft.KeyboardType.NUMBER,
    )
    controls = []

    def selected_pairs():
        pairs = []
        for group in groups:
            gid = str(group["id"])
            value = choices.get(gid)
            if group.get("selection_type") == "single":
                option = next((o for o in group.get("options", []) if str(o["id"]) == str(value)), None)
                if option:
                    pairs.append((group, option))
            else:
                for oid in value or []:
                    option = next((o for o in group.get("options", []) if str(o["id"]) == str(oid)), None)
                    if option:
                        pairs.append((group, option))
        return pairs

    def update_price(e=None):
        unit = base_price
        max_price = 0.0
        for group in groups:
            gid = str(group["id"])
            pairs = [
                (gg, oo) for gg, oo in selected_pairs()
                if str(gg["id"]) == gid
            ]
            if not pairs:
                continue
            if group.get("pricing_mode") == "max":
                max_price = max(max_price, max(float(option.get("price_delta") or 0) for _, option in pairs))
            else:
                unit += sum(float(option.get("price_delta") or 0) for _, option in pairs)
        unit = max(unit, max_price) if max_price else unit
        unit = _customer_price(unit, commission_rate)
        try:
            quantity = max(1, min(99, int(qty.value or 1)))
        except ValueError:
            quantity = 1
        price_text.value = f"${unit * quantity:.2f}"
        page.update()

    def toggle_multi(group_id, option_id, checked):
        current = set(choices.get(group_id) or [])
        if checked:
            current.add(option_id)
        else:
            current.discard(option_id)
        choices[group_id] = list(current)
        update_price()

    for group in groups:
        gid = str(group["id"])
        if group.get("selection_type") == "single":
            dropdown = ft.Dropdown(
                label=group["name"],
                options=[
                    ft.dropdown.Option(
                        key=str(option["id"]),
                        text=f"{option['name']} +${_customer_price(option['price_delta'], commission_rate):.2f}"
                        if float(option.get("price_delta") or 0) > 0 else option["name"],
                    )
                    for option in group.get("options", [])
                ],
                on_change=lambda e, gid=gid: (choices.__setitem__(gid, e.control.value), update_price()),
            )
            if group.get("options"):
                dropdown.value = str(group["options"][0]["id"])
                choices[gid] = dropdown.value
            controls.append(dropdown)
        else:
            is_max = group.get("pricing_mode") == "max"
            boxes = [
                ft.Checkbox(
                    label=(
                        f"{option['name']} ${_customer_price(option['price_delta'], commission_rate):.2f} completo"
                        if is_max and float(option.get("price_delta") or 0) > 0
                        else f"{option['name']} +${_customer_price(option['price_delta'], commission_rate):.2f}"
                        if float(option.get("price_delta") or 0) > 0
                        else option["name"]
                    ),
                    value=is_max and group.get("is_required") and index == 0,
                    on_change=lambda e, gid=gid, oid=str(option["id"]): toggle_multi(gid, oid, e.control.value),
                )
                for index, option in enumerate(group.get("options", []))
            ]
            if is_max and group.get("is_required") and group.get("options"):
                choices[gid] = [str(group["options"][0]["id"])]
            controls.append(
                ft.Column([
                    ft.Text(group["name"], weight=ft.FontWeight.BOLD),
                    *([ft.Text(f"Elige hasta {group['max_selections']} ingredientes", size=11, color=ft.Colors.GREY)] if is_max else []),
                    *boxes,
                ], spacing=2)
            )

    qty.on_change = update_price

    def add(e):
        pairs = selected_pairs()
        for group in groups:
            gid = str(group["id"])
            count = len([1 for selected_group, _ in pairs if str(selected_group["id"]) == gid])
            minimum = int(group.get("min_selections") or 0)
            maximum = int(group.get("max_selections") or 1)
            if group.get("is_required") and count < max(minimum, 1):
                snack(page, f"Elige una opción en {group['name']}", ft.Colors.RED)
                return
            if count < minimum or count > maximum:
                snack(page, f"Revisa las opciones de {group['name']}", ft.Colors.RED)
                return
        try:
            quantity = max(1, min(99, int(qty.value or 1)))
        except ValueError:
            quantity = 1
        option_ids = [str(option["id"]) for _, option in pairs]
        option_names = []
        unit_price = base_price
        max_price = 0.0
        for group in groups:
            gid = str(group["id"])
            group_pairs = [(gg, oo) for gg, oo in pairs if str(gg["id"]) == gid]
            if not group_pairs:
                continue
            if group.get("pricing_mode") == "max":
                max_price = max(
                    max_price,
                    max(float(option.get("price_delta") or 0) for _, option in group_pairs),
                )
                for _, option in group_pairs:
                    option_names.append(
                        f"{group['name']}: {option['name']} (1/{len(group_pairs)})"
                    )
            else:
                unit_price += sum(float(option.get("price_delta") or 0) for _, option in group_pairs)
                for _, option in group_pairs:
                    option_names.append(f"{group['name']}: {option['name']}")
        if max_price:
            unit_price = max(unit_price, max_price)
        unit_price = _customer_price(unit_price, commission_rate)
        key = _cart_line_key(str(item["id"]), option_ids)
        existing = next(
            (c for c in cart
             if (c.get("line_key") or _cart_line_key(c["menu_item_id"], c.get("option_ids", []))) == key),
            None,
        )
        if existing:
            existing["quantity"] += quantity
        else:
            cart.append({
                "menu_item_id": str(item["id"]),
                "quantity": quantity,
                "name": item["name"],
                "price": unit_price,
                "base_price": base_price,
                "option_ids": option_ids,
                "option_names": option_names,
                "line_key": key,
                "restaurant_id": rid,
            })
        page.run_task(sync_cart, list(cart))
        snack(page, f"{item['name']} agregado al carrito")
        close_dlg(page, dlg)
        update_price()

    dlg = ft.AlertDialog(
        title=ft.Text(item["name"], size=16),
        content=ft.Column(
            [*controls, qty, price_text],
            tight=True, width=dialog_width(page), scroll=ft.ScrollMode.AUTO,
        ),
        actions=[
            ft.TextButton("Cancelar", on_click=lambda _: close_dlg(page, dlg)),
            ft.FilledButton("Agregar", on_click=add),
        ],
    )
    open_dlg(page, dlg)


def _customer_price(value, rate: float) -> float:
    try:
        return round(float(value or 0) * (1 + float(rate or 0) / 100), 2)
    except (TypeError, ValueError):
        return 0.0


def _menu_item_card(page: ft.Page, item: dict, rid: str | None = None, is_owner: bool = False, commission_rate: float = 0, is_staff: bool = False):
    item_id = str(item["id"])
    option_groups = item.get("option_groups") or []
    qty = ft.TextField(
        value="0", width=58, height=40, text_size=14,
        text_align=ft.TextAlign.CENTER,
        keyboard_type=ft.KeyboardType.NUMBER,
        content_padding=ft.Padding(2, 6, 2, 6),
    )

    def _current():
        key = _cart_line_key(item_id)
        return next(
            (c for c in cart
             if (c.get("line_key") or _cart_line_key(c["menu_item_id"], c.get("option_ids", []))) == key),
            None,
        )

    def _cart_quantity() -> int:
        ci = _current()
        return ci["quantity"] if ci else 0

    def _set_quantity(value: int, update_field: bool = True):
        value = max(0, min(99, int(value)))
        ci = _current()
        if value == 0:
            if ci:
                cart.remove(ci)
        elif ci:
            ci["quantity"] = value
        else:
            cart.append({
                "menu_item_id": item_id,
                "quantity": value,
                "name": item["name"],
                "price": _customer_price(item["price"], commission_rate),
                "base_price": float(item["price"]),
                "option_ids": [],
                "option_names": [],
                "line_key": _cart_line_key(item_id),
                "restaurant_id": rid,
            })
        if update_field:
            qty.value = str(value)
        page.run_task(sync_cart, list(cart))

    def update_qty_display():
        qty.value = str(_cart_quantity())
        page.update()

    def on_qty_change(e):
        raw = (e.control.value or "").strip()
        try:
            value = int(raw) if raw else 0
        except ValueError:
            value = 0
        # Do not rewrite the field while the user is typing.
        _set_quantity(value, update_field=False)

    def on_qty_blur(e):
        qty.value = str(_cart_quantity())
        page.update()

    qty.on_change = on_qty_change
    qty.on_blur = on_qty_blur

    async def add(e):
        _set_quantity(_cart_quantity() + 1)
        page.update()

    async def remove(e):
        _set_quantity(_cart_quantity() - 1)
        page.update()

    qty.value = str(_cart_quantity())

    img_url = item.get("image_url")
    item_img = ft.Image(src=f"{api.api_url}{img_url}", width=50, height=50, border_radius=6, fit=ft.BoxFit.COVER) if img_url else None

    def _open_image(e):
        if not img_url:
            return
        dlg = ft.AlertDialog(
            title=ft.Text(item["name"], size=16),
            content=ft.Image(
                src=f"{api.api_url}{img_url}",
                width=dialog_width(page, max_width=320), height=dialog_width(page, max_width=320), fit=ft.BoxFit.CONTAIN,
            ),
            actions=[ft.TextButton("Cerrar", on_click=lambda _: close_dlg(page, dlg))],
        )
        open_dlg(page, dlg)

    item_image_widget = (
        ft.GestureDetector(content=item_img, on_tap=_open_image)
        if item_img else ft.Container(width=0)
    )

    async def _upload_item_image(e):
        path = pick_image_file()
        if not path or not rid:
            return
        try:
            await api.upload_menu_item_image(rid, str(item["id"]), path)
            snack(page, "Imagen actualizada")
        except ApiError as ex:
            snack(page, f"Error: {ex.detail}", ft.Colors.RED)
        page.update()

    return ft.Container(
        content=ft.Row([
            item_image_widget,
            ft.Column([
                ft.Row([
                    ft.Text(item["name"], size=15, weight=ft.FontWeight.BOLD, expand=True, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    *([ft.IconButton(ft.Icons.IMAGE, icon_size=16, on_click=lambda e: page.run_task(_upload_item_image, e))] if is_owner else []),
                ]),
                ft.Text(item.get("description", "") or "", size=12, color=ft.Colors.GREY),
                ft.Text(f"${_customer_price(item['price'], commission_rate) if not is_owner else float(item['price']):.2f}", size=14),
            ], expand=True),
            ft.Row([]) if is_staff and not is_owner else (ft.Row([
                ft.FilledTonalButton(
                    "Personalizar", icon=ft.Icons.TUNE,
                    on_click=lambda e: _open_item_customizer(page, item, rid, commission_rate),
                )
            ]) if option_groups else ft.Row([
                ft.IconButton(ft.Icons.REMOVE_CIRCLE_OUTLINE, on_click=remove),
                qty,
                ft.IconButton(ft.Icons.ADD_CIRCLE, on_click=add),
            ])),
        ]),
        padding=10,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        border_radius=10,
    )
