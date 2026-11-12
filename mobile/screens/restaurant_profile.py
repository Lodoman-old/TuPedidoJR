import math
import re

import flet as ft

from mobile.api import api, ApiError
from mobile.location_service import compose_address, current_position, pick_colonia, reverse_address
from mobile.map_widget import map_image, update_map
from mobile.server_selector import open_server_dialog
from mobile.utils import pick_image_file, snack

DAY_NAMES = ["Domingo", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
ROLE_LABELS = {
    "owner": "Dueño",
    "manager": "Encargado",
    "admin": "Administrador",
}
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def restaurant_profile_view(page: ft.Page, rid: str):
    loading = ft.ProgressBar(visible=False)
    error_text = ft.Text("", color=ft.Colors.RED)
    denied = ft.Text(
        "Solo el dueño o el encargado pueden editar el perfil del negocio.",
        color=ft.Colors.ORANGE,
        visible=False,
    )
    content = ft.Column(
        scroll=ft.ScrollMode.AUTO,
        expand=True,
        spacing=8,
        visible=False,
    )

    # ===== Datos del negocio =====
    name = ft.TextField(label="Nombre del negocio")
    cuisine = ft.TextField(label="Giro", hint_text="Pizza, Tacos, Sushi...")
    description = ft.TextField(label="Descripción", multiline=True, min_lines=2)
    phone = ft.TextField(label="Teléfono", keyboard_type=ft.KeyboardType.PHONE)
    delivery_mode = ft.Dropdown(
        label="Tipo de entrega",
        options=[
            ft.dropdown.Option(key="platform", text="Repartidor de TuPedidoJR"),
            ft.dropdown.Option(key="own", text="Repartidor propio"),
        ],
        value="platform",
    )
    pickup = ft.Switch(label="Permitir recoger en el restaurante")
    is_open = ft.Switch(label="Recibiendo pedidos")
    public_page = ft.Switch(label="Página pública activada")
    role_label = ft.Text("", size=11, color=ft.Colors.GREY)
    business_msg = ft.Text("", size=11)

    # ===== Logo =====
    logo_img = ft.Image(src="", width=84, height=84, border_radius=12, fit=ft.BoxFit.COVER, visible=False)
    logo_icon = ft.Icon(ft.Icons.STORE, size=42, color=ft.Colors.GREY)
    logo_box = ft.Container(
        content=ft.Stack([logo_icon, logo_img]),
        width=84, height=84, border_radius=12,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        alignment=ft.Alignment.CENTER,
    )
    logo_msg = ft.Text("", size=11)

    async def upload_logo(e):
        path = pick_image_file()
        if not path:
            return
        logo_msg.value = "Subiendo logo..."
        logo_msg.color = ft.Colors.GREY
        page.update()
        try:
            await api.upload_restaurant_logo(rid, path)
            logo_msg.value = "Logo actualizado"
            logo_msg.color = ft.Colors.GREEN
            await load()
        except ApiError as ex:
            logo_msg.value = f"Error: {ex.detail}"
            logo_msg.color = ft.Colors.RED
        page.update()

    # ===== Horario =====
    schedule_state: list[dict] = []
    schedule_col = ft.Column(spacing=4)

    def render_schedule():
        schedule_col.controls.clear()
        for day in range(7):
            entries = [(i, e) for i, e in enumerate(schedule_state) if e["day_of_week"] == day]
            rows = []
            if not entries:
                rows.append(ft.Text("Cerrado", size=11, color=ft.Colors.GREY))
            for index, entry in entries:
                open_field = ft.TextField(
                    value=entry["open_time"], width=88, text_size=12,
                    hint_text="HH:MM", content_padding=8,
                )
                close_field = ft.TextField(
                    value=entry["close_time"], width=88, text_size=12,
                    hint_text="HH:MM", content_padding=8,
                )
                open_field.on_change = lambda e, i=index: _update_entry(i, "open_time", e.control.value)
                close_field.on_change = lambda e, i=index: _update_entry(i, "close_time", e.control.value)
                rows.append(ft.Row([
                    open_field,
                    ft.Text("a", size=12),
                    close_field,
                    ft.IconButton(
                        ft.Icons.DELETE_OUTLINE, icon_size=18,
                        tooltip="Quitar turno",
                        on_click=lambda e, i=index: _remove_entry(i),
                    ),
                ], spacing=4, wrap=True))
            schedule_col.controls.append(ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Text(DAY_NAMES[day], size=12, weight=ft.FontWeight.BOLD),
                        ft.TextButton("+ turno", on_click=lambda e, d=day: _add_entry(d)),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    *rows,
                ], spacing=2),
                padding=ft.Padding(0, 4, 0, 6),
            ))
        page.update()

    def _add_entry(day: int):
        schedule_state.append({"day_of_week": day, "open_time": "09:00", "close_time": "22:00"})
        render_schedule()

    def _update_entry(index: int, field: str, value: str):
        if 0 <= index < len(schedule_state):
            schedule_state[index][field] = value

    def _remove_entry(index: int):
        if 0 <= index < len(schedule_state):
            schedule_state.pop(index)
            render_schedule()

    schedule_msg = ft.Text("", size=11)

    async def save_schedule(e):
        entries = []
        for entry in schedule_state:
            open_time = (entry.get("open_time") or "").strip()
            close_time = (entry.get("close_time") or "").strip()
            if not TIME_RE.match(open_time) or not TIME_RE.match(close_time):
                schedule_msg.value = "Usa el formato HH:MM (ej. 09:00)."
                schedule_msg.color = ft.Colors.RED
                page.update()
                return
            entries.append({
                "day_of_week": entry["day_of_week"],
                "open_time": open_time,
                "close_time": close_time,
                "is_closed": False,
            })
        try:
            await api.update_restaurant_schedule(rid, entries)
            schedule_msg.value = "Horario guardado"
            schedule_msg.color = ft.Colors.GREEN
            snack(page, "Horario guardado")
        except ApiError as ex:
            schedule_msg.value = ex.detail
            schedule_msg.color = ft.Colors.RED
        page.update()

    # ===== Ubicación =====
    cp = ft.TextField(label="C.P.", width=118, max_length=5, keyboard_type=ft.KeyboardType.NUMBER)
    colonia = ft.Dropdown(label="Colonia", expand=True, options=[], text_size=13)
    street = ft.TextField(label="Calle y número")
    geo_msg = ft.Text("", size=11, color=ft.Colors.GREY)
    coords = {"lat": 20.644, "lng": -100.993}
    coords_ready = {"value": False}
    cp_center = {}
    map_size = 280
    map_zoom = 16
    map_container, map_img, _ = map_image(coords["lat"], coords["lng"], zoom=map_zoom, size=map_size)
    map_hint = ft.Text("Toca el mapa para mover el pin.", size=11, color=ft.Colors.GREY)

    def _refresh_map():
        update_map(map_img, None, coords["lat"], coords["lng"], zoom=map_zoom, size=map_size)

    def _full_address() -> str:
        return compose_address(
            (street.value or "").strip(),
            (colonia.value or "").strip(),
            re.sub(r"\D", "", cp.value or "")[:5],
        )

    def _set_colonia(name_value: str):
        if not name_value:
            return
        names = [o.key for o in colonia.options]
        chosen = pick_colonia(names, name_value) or name_value
        if chosen not in names:
            colonia.options.append(ft.dropdown.Option(key=chosen, text=chosen))
        colonia.value = chosen

    async def _load_cp_colonias(cp_value: str, selected: str = ""):
        if len(cp_value or "") != 5:
            return
        try:
            data = await api.get_colonias(cp_value)
        except Exception:
            return
        names = [c.get("nombre") for c in (data.get("colonias") or []) if c.get("nombre")]
        if data.get("lat") is not None and data.get("lng") is not None:
            cp_center["lat"] = float(data["lat"])
            cp_center["lng"] = float(data["lng"])
        colonia.options = [ft.dropdown.Option(key=n, text=n) for n in names]
        if selected:
            _set_colonia(selected)
        elif len(names) == 1:
            colonia.value = names[0]
        page.update()

    def _on_cp_change(e):
        value = re.sub(r"\D", "", cp.value or "")[:5]
        if value != (cp.value or ""):
            cp.value = value
        coords_ready["value"] = False
        if len(value) == 5:
            page.run_task(_load_cp_colonias, value)
        page.update()

    cp.on_change = _on_cp_change

    def _on_text_change(e):
        coords_ready["value"] = False

    street.on_change = _on_text_change
    colonia.on_change = _on_text_change

    def on_map_tap(e):
        pos = getattr(e, "local_position", None)
        if pos is None:
            return
        lat, lng = coords["lat"], coords["lng"]
        meters_per_pixel = 156543.03392 * math.cos(math.radians(lat)) / (2 ** map_zoom)
        dx = pos.x - map_size / 2
        dy = pos.y - map_size / 2
        coords["lat"] = lat - (dy * meters_per_pixel) / 111320.0
        coords["lng"] = lng + (dx * meters_per_pixel) / (
            111320.0 * max(math.cos(math.radians(lat)), 0.1)
        )
        coords_ready["value"] = True
        _refresh_map()
        geo_msg.value = "Pin ajustado. Guarda para confirmar la ubicación."
        geo_msg.color = ft.Colors.GREEN
        page.update()

    map_gesture = ft.GestureDetector(content=map_container, on_tap_down=on_map_tap)

    async def _apply_device(auto: bool = False):
        geo_msg.value = "Obteniendo ubicación del dispositivo..."
        geo_msg.color = ft.Colors.GREY
        page.update()
        pos = await current_position()
        coords["lat"] = float(pos["lat"])
        coords["lng"] = float(pos["lng"])
        coords_ready["value"] = True
        found = await reverse_address(coords["lat"], coords["lng"])
        if found["street"]:
            street.value = found["street"]
        if found["cp"]:
            cp.value = found["cp"]
            await _load_cp_colonias(found["cp"], found["colonia"])
        elif found["colonia"]:
            _set_colonia(found["colonia"])
        _refresh_map()
        parts = [found["street"], found["colonia"], f"C.P. {found['cp']}" if found["cp"] else ""]
        parts = [p for p in parts if p]
        if parts:
            geo_msg.value = (
                f"{'Ubicación detectada' if auto else 'Ubicación aplicada'}: "
                f"{', '.join(parts)}. Corrige la calle o mueve el pin."
            )
            geo_msg.color = ft.Colors.GREEN
        else:
            geo_msg.value = f"{pos['source']} aplicada. Escribe calle, colonia y C.P."
            geo_msg.color = ft.Colors.ORANGE
        page.update()

    def use_device(e):
        page.run_task(_apply_device, False)

    async def search_street(e):
        address_text = _full_address()
        street_value = (street.value or "").strip()
        if len(street_value) < 3:
            geo_msg.value = "Escribe calle y número."
            geo_msg.color = ft.Colors.RED
            page.update()
            return
        geo_msg.value = "Buscando la calle..."
        geo_msg.color = ft.Colors.GREY
        page.update()
        try:
            cp_value = re.sub(r"\D", "", cp.value or "")[:5]
            colonia_value = (colonia.value or "").strip()
            results = []
            if cp_value and colonia_value:
                results = await api.geocode_structured(street_value, colonia_value, cp_value)
            if not results:
                results = await api.geocode_address(
                    f"{address_text}, Santa Cruz de Juventino Rosas, Guanajuato, México"
                )
            if not results:
                geo_msg.value = "No encontramos la calle. Ajusta el pin en el mapa."
                geo_msg.color = ft.Colors.ORANGE
                page.update()
                return
            coords["lat"] = float(results[0]["lat"])
            coords["lng"] = float(results[0]["lng"])
            coords_ready["value"] = True
            _refresh_map()
            geo_msg.value = f"Calle encontrada: {results[0].get('display_name', address_text)}. Revisa el pin y guarda."
            geo_msg.color = ft.Colors.GREEN
        except ApiError as ex:
            geo_msg.value = ex.detail
            geo_msg.color = ft.Colors.RED
        except Exception as ex:
            geo_msg.value = f"No se pudo ubicar: {ex}"
            geo_msg.color = ft.Colors.RED
        page.update()

    async def save_location(e):
        address_text = _full_address()
        if not (street.value or "").strip():
            geo_msg.value = "Escribe la calle y el número."
            geo_msg.color = ft.Colors.RED
            page.update()
            return
        if not coords_ready["value"]:
            try:
                street_value = (street.value or "").strip()
                cp_value = re.sub(r"\D", "", cp.value or "")[:5]
                colonia_value = (colonia.value or "").strip()
                results = []
                if cp_value and colonia_value:
                    results = await api.geocode_structured(street_value, colonia_value, cp_value)
                if not results:
                    results = await api.geocode_address(
                        f"{address_text}, Santa Cruz de Juventino Rosas, Guanajuato, México"
                    )
                if results:
                    coords["lat"] = float(results[0]["lat"])
                    coords["lng"] = float(results[0]["lng"])
                    coords_ready["value"] = True
                    _refresh_map()
                elif cp_center.get("lat") is not None:
                    coords["lat"] = float(cp_center["lat"])
                    coords["lng"] = float(cp_center["lng"])
                    coords_ready["value"] = True
                    _refresh_map()
            except Exception:
                pass
        if not coords_ready["value"]:
            geo_msg.value = "No pudimos ubicar la dirección. Usa tu ubicación o toca el mapa."
            geo_msg.color = ft.Colors.RED
            page.update()
            return
        try:
            await api.update_restaurant_location(rid, coords["lat"], coords["lng"], address_text)
            geo_msg.value = f"Ubicación guardada: {address_text}"
            geo_msg.color = ft.Colors.GREEN
            snack(page, "Ubicación guardada")
        except ApiError as ex:
            geo_msg.value = ex.detail
            geo_msg.color = ft.Colors.RED
        page.update()

    # ===== Carga =====
    async def load():
        nonlocal loading
        loading.visible = True
        error_text.value = ""
        page.update()
        try:
            r = await api.get_restaurant(rid)
            role = r.get("viewer_role")
            role_label.value = ROLE_LABELS.get(role, role or "")
            if role not in ("owner", "manager", "admin"):
                denied.visible = True
                content.visible = False
                return
            denied.visible = False
            content.visible = True
            name.value = r.get("name") or ""
            cuisine.value = r.get("cuisine") or ""
            description.value = r.get("description") or ""
            phone.value = r.get("phone") or ""
            delivery_mode.value = "own" if r.get("delivery_mode") == "own" else "platform"
            pickup.value = bool(r.get("pickup_enabled"))
            is_open.value = bool(r.get("is_open"))
            public_page.value = bool(r.get("public_page_enabled"))
            logo_url = r.get("logo_url")
            if logo_url:
                logo_img.src = logo_url
                logo_img.visible = True
                logo_icon.visible = False
            else:
                logo_img.visible = False
                logo_icon.visible = True
            await load_location()
            await load_schedule()
            _refresh_map()
        except ApiError as ex:
            error_text.value = ex.detail
        except Exception as ex:
            error_text.value = str(ex)
        finally:
            loading.visible = False
            page.update()

    async def load_location():
        loc = await api.get_restaurant_location(rid)
        if loc.get("lat") is not None and loc.get("lng") is not None:
            coords["lat"] = float(loc["lat"])
            coords["lng"] = float(loc["lng"])
            coords_ready["value"] = True
            _refresh_map()
            if loc.get("address"):
                street.value = loc["address"]
            found = await reverse_address(coords["lat"], coords["lng"])
            if found["cp"]:
                cp.value = found["cp"]
                await _load_cp_colonias(found["cp"], found["colonia"])
            elif found["colonia"]:
                _set_colonia(found["colonia"])
            if found["street"]:
                street.value = found["street"]
            elif loc.get("address"):
                street.value = loc["address"]
            if not (cp.value or "").strip() and loc.get("address"):
                match = re.search(r"\b(\d{5})\b", loc["address"])
                if match:
                    cp.value = match.group(1)
                    await _load_cp_colonias(match.group(1))
        elif loc.get("address"):
            street.value = loc["address"]

        if not (street.value or "").strip() and not (cp.value or "").strip():
            await _apply_device(True)

    async def load_schedule():
        schedule_state.clear()
        try:
            rows = await api.get_restaurant_schedule(rid)
        except ApiError:
            rows = []
        for row in rows:
            schedule_state.append({
                "day_of_week": int(row.get("day_of_week") or 0),
                "open_time": str(row.get("open_time") or "09:00")[:5],
                "close_time": str(row.get("close_time") or "22:00")[:5],
            })
        render_schedule()

    async def save_business(e):
        if not (name.value or "").strip():
            business_msg.value = "El nombre es obligatorio"
            business_msg.color = ft.Colors.RED
            page.update()
            return
        try:
            await api.update_restaurant_profile(
                rid,
                name=(name.value or "").strip(),
                cuisine=(cuisine.value or "").strip() or None,
                description=(description.value or "").strip() or None,
                phone=(phone.value or "").strip() or None,
                delivery_mode=delivery_mode.value or "platform",
                pickup_enabled=bool(pickup.value),
                is_open=bool(is_open.value),
                public_page_enabled=bool(public_page.value),
            )
            business_msg.value = "Datos guardados"
            business_msg.color = ft.Colors.GREEN
            snack(page, "Datos del negocio actualizados")
        except ApiError as ex:
            business_msg.value = ex.detail
            business_msg.color = ft.Colors.RED
        page.update()

    content.controls = [
        ft.Text("Datos del negocio", size=16, weight=ft.FontWeight.BOLD),
        role_label,
        name, cuisine, description, phone, delivery_mode,
        pickup, is_open, public_page,
        business_msg,
        ft.FilledButton("Guardar datos", icon=ft.Icons.CHECK, on_click=save_business),
        ft.Divider(height=1),
        ft.Text("Logo del negocio", size=16, weight=ft.FontWeight.BOLD),
        ft.Row([
            logo_box,
            ft.Column([
                ft.FilledTonalButton("Cambiar logo", icon=ft.Icons.UPLOAD_FILE, on_click=upload_logo),
                ft.Text("Se recorta a un cuadrado y se convierte a WebP.", size=10, color=ft.Colors.GREY),
                logo_msg,
            ], tight=True, spacing=2, expand=True),
        ], spacing=10),
        ft.Divider(height=1),
        ft.Text("Horario de atención", size=16, weight=ft.FontWeight.BOLD),
        ft.Text("Los días sin turnos se consideran cerrados.", size=11, color=ft.Colors.GREY),
        schedule_col,
        schedule_msg,
        ft.FilledButton("Guardar horario", icon=ft.Icons.SCHEDULE, on_click=save_schedule),
        ft.Divider(height=1),
        ft.Text("Dirección y ubicación", size=16, weight=ft.FontWeight.BOLD),
        ft.Text(
            "Esta dirección se usa para envíos y mandados. Si no hay dirección, intentamos usar la ubicación del dispositivo.",
            size=11, color=ft.Colors.GREY,
        ),
        ft.Row([cp, colonia], spacing=6),
        street,
        ft.Row([
            ft.FilledTonalButton("Usar ubicación del dispositivo", icon=ft.Icons.MY_LOCATION, on_click=use_device),
            ft.OutlinedButton("Buscar calle", icon=ft.Icons.SEARCH, on_click=lambda e: page.run_task(search_street, e)),
        ], wrap=True),
        geo_msg,
        map_gesture,
        map_hint,
        ft.FilledButton("Guardar ubicación", icon=ft.Icons.LOCATION_ON, on_click=save_location),
        ft.Container(height=20),
    ]

    page.run_task(load)

    return ft.View(
        route=f"/restaurant-profile/{rid}",
        controls=[
            ft.AppBar(
                title=ft.Text("Perfil del negocio"),
                leading=ft.IconButton(
                    ft.Icons.ARROW_BACK,
                    on_click=lambda _: page.run_task(page.push_route, f"/restaurant/{rid}"),
                ),
                actions=[
                    ft.IconButton(
                        ft.Icons.DNS,
                        tooltip="Servidor",
                        on_click=lambda _: open_server_dialog(page),
                    ),
                ],
            ),
            ft.SafeArea(ft.Column([
                loading,
                error_text,
                denied,
                content,
            ], expand=True, spacing=8)),
        ],
    )
