import math
import re
import time

import flet as ft
from mobile.api import api, ApiError
from mobile import secure_auth
from mobile.location_service import compose_address, current_position, pick_colonia, reverse_address
from mobile.map_widget import map_image, update_map
from mobile.server_selector import open_server_dialog
from mobile.utils import open_dlg, close_dlg, dialog_width


def profile_view(page: ft.Page):
    name_text = ft.Text(size=22, weight=ft.FontWeight.BOLD)
    email_text = ft.Text(size=14, color=ft.Colors.GREY)
    points_text = ft.Text("0 puntos", size=16, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE)
    referral_text = ft.Text("", size=13, selectable=True)
    loyalty_card = ft.Container(
        content=ft.Column([
            ft.Row([ft.Icon(ft.Icons.STARS, color=ft.Colors.BLUE), ft.Text("Puntos de lealtad", weight=ft.FontWeight.BOLD)]),
            points_text,
            ft.Text("Comparte tu código y ambos ganan puntos.", size=11, color=ft.Colors.GREY),
            referral_text,
        ], spacing=4),
        padding=12, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH, border_radius=10,
        visible=False,
    )
    bio_switch = ft.Switch(label="Entrar con huella o rostro", value=False)
    bio_msg = ft.Text("", size=11, color=ft.Colors.GREY)
    bio_card = ft.Container(
        content=ft.Column([
            ft.Row([ft.Icon(ft.Icons.FINGERPRINT, color=ft.Colors.BLUE), ft.Text("Seguridad", weight=ft.FontWeight.BOLD)]),
            bio_switch,
            bio_msg,
        ], spacing=4),
        padding=12, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH, border_radius=10,
        visible=False,
    )
    server_text = ft.Text(api.api_url, size=12, color=ft.Colors.GREY)

    def refresh_server():
        server_text.value = api.api_url
        page.update()

    server_card = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.DNS, color=ft.Colors.BLUE),
                ft.Text("Servidor", weight=ft.FontWeight.BOLD),
            ], spacing=6),
            server_text,
            ft.FilledTonalButton(
                "Cambiar servidor",
                icon=ft.Icons.SWAP_HORIZ,
                on_click=lambda _: open_server_dialog(page, refresh_server),
            ),
            ft.Text("Cambia entre local y producción. Se cerrará la sesión.", size=10, color=ft.Colors.GREY),
        ], spacing=4),
        padding=12, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH, border_radius=10,
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
                await secure_auth.save_session(api.token, email_text.value or "", name_text.value or "")
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
    loading = ft.ProgressBar(visible=False)
    error_text = ft.Text("", color=ft.Colors.RED)
    addr_list = ft.Column(spacing=8)

    async def load():
        loading.visible = True
        page.update()
        try:
            prof = await api.get_profile()
            name_text.value = prof["name"]
            email_text.value = prof["email"]
            points_text.value = f"{int(prof.get('loyalty_points') or 0)} puntos"
            try:
                loyalty_config = await api.payment_config()
            except Exception:
                loyalty_config = {}
            loyalty_visible = bool(
                loyalty_config.get("loyalty_enabled", True)
                and loyalty_config.get("loyalty_visible", True)
            )
            if loyalty_visible and prof.get("referral_code"):
                referral_text.value = f"Código de invitación: {prof['referral_code']}"
                loyalty_card.visible = True
            addrs = await api.list_addresses()
            _render_addresses(addrs)
        except ApiError as ex:
            error_text.value = ex.detail
        finally:
            loading.visible = False
            page.update()

    def _render_addresses(addrs: list):
        addr_list.controls.clear()
        for a in addrs:
            addr_list.controls.append(_addr_card(page, a, load))
        addr_list.controls.append(
            ft.TextButton("+ Agregar dirección", on_click=lambda _: _open_form(page, None, load))
        )

    page.run_task(load)

    appbar = ft.AppBar(title=ft.Text("Mi perfil"))

    return ft.View(
        route="/profile",
        controls=[
            appbar,
            ft.SafeArea(ft.Column([
                error_text, loading,
                name_text, email_text,
                loyalty_card,
                bio_card,
                server_card,
                ft.Divider(),
                ft.Text("Direcciones guardadas", size=16, weight=ft.FontWeight.BOLD),
                addr_list,
            ], scroll=ft.ScrollMode.AUTO, expand=True))
        ]
    )


def _addr_card(page: ft.Page, a: dict, reload_cb):
    info = ft.Column([
        ft.Row([
            ft.Text(
                a["name"], weight=ft.FontWeight.BOLD, expand=True,
                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
            ),
            ft.Container(
                ft.Text("Predeterminada", size=10, color=ft.Colors.WHITE),
                bgcolor=ft.Colors.GREEN, border_radius=20,
                padding=ft.Padding(8, 2, 8, 2),
            ) if a.get("is_default") else ft.Container(),
        ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ft.Text(
            a["address"], size=12, color=ft.Colors.GREY_700,
            max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
        ),
    ], spacing=2, expand=True)
    return ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.LOCATION_ON, size=20, color=ft.Colors.RED),
            info,
            ft.IconButton(
                ft.Icons.EDIT, icon_size=18, tooltip="Editar",
                on_click=lambda _: _open_form(page, a, reload_cb),
            ),
            ft.IconButton(
                ft.Icons.DELETE_OUTLINE, icon_size=18, tooltip="Eliminar",
                on_click=lambda _: page.run_task(_delete_addr, a["id"], reload_cb),
            ),
        ], spacing=2, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=10, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH, border_radius=10,
    )


async def _delete_addr(addr_id: str, reload_cb):
    try:
        await api.delete_address(addr_id)
        await reload_cb()
    except ApiError:
        pass


def _split_saved_address(raw: str) -> tuple[str, str, str]:
    """Separa calle, C.P. y colonia de una dirección guardada."""
    text = (raw or "").strip()
    if not text:
        return "", "", ""
    cp_match = re.search(r"(?:C\.?P\.?|CP)\s*(\d{5})", text, re.IGNORECASE)
    cp = cp_match.group(1) if cp_match else ""
    if not cp:
        match = re.search(r"\b(\d{5})\b", text)
        if match:
            cp = match.group(1)
    parts = [part.strip() for part in text.split(",") if part.strip()]
    street = parts[0] if parts else ""
    colonia = ""
    for part in parts[1:]:
        if re.search(r"(?:C\.?P\.?|CP)\s*\d{5}", part, re.IGNORECASE) or re.fullmatch(r"\d{5}", part):
            continue
        colonia = part
        break
    return street, cp, colonia


def _open_form(page: ft.Page, existing: dict | None, reload_cb):
    existing_street, existing_cp, existing_colonia = _split_saved_address(
        (existing or {}).get("address", "")
    )
    name = ft.TextField(label="Nombre (ej: Casa, Trabajo)", value=existing["name"] if existing else "")
    address = ft.TextField(label="Calle y número", multiline=False, value=existing_street if existing else "")
    cp = ft.TextField(
        label="C.P.", width=118, max_length=5,
        keyboard_type=ft.KeyboardType.NUMBER,
        value=existing_cp if existing else "",
    )
    colonia = ft.Dropdown(
        label="Colonia", expand=True, options=[], text_size=13,
        value=(existing_colonia or None) if existing else None,
    )
    notes = ft.TextField(label="Notas (opcional)", value=existing.get("notes", "") if existing else "")
    is_default = ft.Checkbox(label="Dirección predeterminada", value=existing.get("is_default", False) if existing else False)
    error_t = ft.Text("", color=ft.Colors.RED)
    saving = ft.ProgressBar(visible=False)
    geo_msg = ft.Text("", size=11, color=ft.Colors.GREY)
    coords = {
        "lat": (existing or {}).get("location", {}).get("lat", 20.644),
        "lng": (existing or {}).get("location", {}).get("lng", -100.993),
    }
    existing_full = (
        compose_address(existing_street, existing_colonia, existing_cp) if existing else ""
    )
    geo_state = {"address": existing_full}

    map_size = 280
    map_zoom = 16
    map_container, map_img, _ = map_image(coords["lat"], coords["lng"], zoom=map_zoom, size=map_size)
    map_hint = ft.Text("Toca o arrastra el mapa para mover el pin.", size=11, color=ft.Colors.GREY)

    def _refresh_map():
        update_map(map_img, None, coords["lat"], coords["lng"], zoom=map_zoom, size=map_size)

    def _mark_manual_location(message: str):
        geo_state["address"] = _full_address()
        _refresh_map()
        geo_msg.value = message
        geo_msg.color = ft.Colors.GREEN
        page.update()

    def _set_colonia(name: str):
        if not name:
            return
        names = [o.key for o in colonia.options]
        chosen = pick_colonia(names, name) or name
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
        if len(value) == 5:
            page.run_task(_load_cp_colonias, value)
        page.update()

    cp.on_change = _on_cp_change

    def _full_address() -> str:
        return compose_address(
            (address.value or "").strip(),
            (colonia.value or "").strip(),
            re.sub(r"\D", "", cp.value or "")[:5],
        )

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
        _mark_manual_location("Punto ajustado en el mapa")

    async def _apply_device(auto: bool = False):
        geo_msg.value = "Obteniendo ubicación del dispositivo..."
        geo_msg.color = ft.Colors.GREY
        page.update()
        pos = await current_position()
        coords["lat"] = float(pos["lat"])
        coords["lng"] = float(pos["lng"])
        found = await reverse_address(coords["lat"], coords["lng"])
        if found["street"]:
            address.value = found["street"]
        if found["cp"]:
            cp.value = found["cp"]
            await _load_cp_colonias(found["cp"], found["colonia"])
        elif found["colonia"]:
            _set_colonia(found["colonia"])
        _refresh_map()
        geo_state["address"] = _full_address()
        parts = [found["street"], found["colonia"], f"C.P. {found['cp']}" if found["cp"] else ""]
        parts = [p for p in parts if p]
        if parts:
            geo_msg.value = f"{'Ubicación detectada' if auto else 'Ubicación aplicada'}: {', '.join(parts)}. Corrige la calle o mueve el pin."
            geo_msg.color = ft.Colors.GREEN
        else:
            geo_msg.value = f"{pos['source']} aplicada. Escribe calle, colonia y C.P."
            geo_msg.color = ft.Colors.ORANGE
        page.update()

    def use_device_location(e):
        page.run_task(_apply_device, False)

    async def _geocode() -> bool:
        street = (address.value or "").strip()
        cp_value = re.sub(r"\D", "", cp.value or "")[:5]
        colonia_value = (colonia.value or "").strip()
        full = compose_address(street, colonia_value, cp_value)
        if len(street) < 3:
            geo_msg.value = "Escribe calle y número"
            geo_msg.color = ft.Colors.RED
            page.update()
            return False
        geo_msg.value = "Buscando dirección..."
        geo_msg.color = ft.Colors.GREY
        page.update()
        try:
            results = []
            if cp_value and colonia_value:
                results = await api.geocode_structured(street, colonia_value, cp_value)
            if not results:
                results = await api.geocode_address(f"{full}, Santa Cruz de Juventino Rosas, Guanajuato, México")
            if not results:
                raise ValueError("No se encontró la dirección")
            coords["lat"] = float(results[0]["lat"])
            coords["lng"] = float(results[0]["lng"])
            geo_state["address"] = full
            _refresh_map()
            geo_msg.value = results[0].get("display_name", "Ubicación encontrada")
            geo_msg.color = ft.Colors.GREEN
            return True
        except Exception as ex:
            geo_msg.value = f"No se pudo ubicar: {ex}"
            geo_msg.color = ft.Colors.RED
            return False
        finally:
            page.update()

    geocode_btn = ft.FilledTonalButton("Buscar ubicación", on_click=lambda e: page.run_task(_geocode))
    device_btn = ft.OutlinedButton(
        "Usar GPS del dispositivo",
        icon=ft.Icons.MY_LOCATION,
        on_click=use_device_location,
    )
    map_gesture = ft.GestureDetector(content=map_container, on_tap_down=on_map_tap)
    _last_refresh = {"t": 0.0}

    def on_map_pan(e):
        delta = getattr(e, "local_delta", None)
        if delta is None:
            return
        lat, lng = coords["lat"], coords["lng"]
        meters_per_pixel = 156543.03392 * math.cos(math.radians(lat)) / (2 ** map_zoom)
        coords["lat"] = lat - (delta.y * meters_per_pixel) / 111320.0
        coords["lng"] = lng + (delta.x * meters_per_pixel) / (
            111320.0 * max(math.cos(math.radians(lat)), 0.1)
        )
        now = time.monotonic()
        if now - _last_refresh["t"] >= 0.35:
            _last_refresh["t"] = now
            _refresh_map()
            page.update()

    def on_map_pan_end(e):
        geo_state["address"] = _full_address()
        _refresh_map()
        geo_msg.value = "Pin ajustado. Revisa la calle o usa el GPS si hace falta."
        geo_msg.color = ft.Colors.GREEN
        page.update()

    map_gesture = ft.GestureDetector(
        content=map_container,
        on_tap_down=on_map_tap,
        on_pan_update=on_map_pan,
        on_pan_end=on_map_pan_end,
        drag_interval=120,
    )

    async def save(e):
        full = _full_address()
        if not name.value or len(address.value or "") < 3:
            error_t.value = "Nombre y calle requeridos"
            page.update()
            return
        if geo_state["address"] != full:
            ok = await _geocode()
            if not ok:
                return
            full = _full_address()
        saving.visible = True
        page.update()
        try:
            if existing:
                await api.update_address(existing["id"], name=name.value, address=full, location={"lat": coords["lat"], "lng": coords["lng"]}, notes=notes.value or None, is_default=is_default.value)
            else:
                await api.create_address(name.value, full, coords["lat"], coords["lng"], is_default=is_default.value, notes=notes.value or None)
            close_dlg(page, dlg)
            await reload_cb()
        except ApiError as ex:
            error_t.value = ex.detail
        finally:
            saving.visible = False
            page.update()

    dlg = ft.AlertDialog(
        title=ft.Text("Agregar dirección" if not existing else "Editar dirección"),
        content=ft.Column([
            name,
            ft.Row([cp, colonia], spacing=6),
            address,
            geocode_btn, device_btn, geo_msg,
            map_gesture, map_hint,
            notes, is_default, error_t, saving,
        ], tight=True, width=dialog_width(page), scroll=ft.ScrollMode.AUTO),
        actions=[ft.TextButton("Cancelar", on_click=lambda _: close_dlg(page, dlg)), ft.FilledButton("Guardar", on_click=save)],
    )
    open_dlg(page, dlg)
    if existing_cp:
        page.run_task(_load_cp_colonias, existing_cp, existing_colonia)
    elif not existing and not (address.value or "").strip():
        page.run_task(_apply_device, True)
