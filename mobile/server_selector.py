"""Selector de servidor para la app (local, producción o URL manual)."""

import flet as ft

from mobile.api import api
from mobile import background_location, secure_auth
from mobile.config import get_local_server_url, get_production_server_url
from mobile.utils import close_dlg, open_dlg, snack, dialog_width


def _normalize(url: str) -> str:
    clean = (url or "").strip()
    if not clean:
        return ""
    if not clean.startswith(("http://", "https://")):
        clean = "http://" + clean
    return clean.rstrip("/")


def open_server_dialog(page: ft.Page, on_changed=None):
    current = api.api_url
    local_url = get_local_server_url()
    production_url = get_production_server_url()

    url_field = ft.TextField(
        label="Dirección del servidor",
        value=current,
        keyboard_type=ft.KeyboardType.URL,
        hint_text="http://localhost:8080",
    )
    message = ft.Text("", size=12, color=ft.Colors.GREY)
    has_session = bool(api.token)

    def set_url(value: str):
        url_field.value = value
        message.value = ""
        page.update()

    def refresh_targets():
        message.value = f"Servidor actual: {current}"
        message.color = ft.Colors.GREY
        page.update()

    refresh_targets()

    async def apply_change(new_url: str, dialog):
        normalized = _normalize(new_url)
        if not normalized:
            message.value = "Escribe una dirección válida."
            message.color = ft.Colors.RED
            page.update()
            return

        if normalized == current:
            close_dlg(page, dialog)
            return

        had_token = bool(api.token)
        if had_token:
            # Limpia el carrito del servidor anterior antes de cambiar.
            try:
                await api.save_cart_snapshot([], None)
            except Exception:
                pass

        final_url = api.set_server_url(normalized)
        if had_token:
            api.clear_token()
            try:
                await secure_auth.clear_session()
            except Exception:
                pass
            background_location.set_enabled(False)
            try:
                from mobile import main as app_main
                app_main._is_dp = False
            except Exception:
                pass
            try:
                from mobile.screens.restaurant_detail import cart
                cart.clear()
            except Exception:
                pass
            close_dlg(page, dialog)
            snack(page, f"Servidor: {final_url}. Inicia sesión de nuevo.")
            await page.push_route("/login")
        else:
            close_dlg(page, dialog)
            snack(page, f"Servidor actualizado: {final_url}")
            if on_changed:
                result = on_changed()
                if result is not None:
                    await result
            page.update()

    def save(e):
        normalized = _normalize(url_field.value)
        if not normalized:
            message.value = "Escribe una dirección válida."
            message.color = ft.Colors.RED
            page.update()
            return
        if not has_session:
            page.run_task(apply_change, normalized, dialog)
            return

        confirm = ft.AlertDialog(
            title=ft.Text("Cambiar de servidor"),
            content=ft.Text(
                "Se cerrará tu sesión actual y volverás a la pantalla de login "
                "para entrar en el nuevo servidor. ¿Continuar?",
                size=13,
            ),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: close_dlg(page, confirm)),
                ft.FilledButton(
                    "Cambiar y salir",
                    on_click=lambda _: (
                        close_dlg(page, confirm),
                        page.run_task(apply_change, normalized, dialog),
                    ),
                ),
            ],
        )
        open_dlg(page, confirm)

    dialog = ft.AlertDialog(
        title=ft.Text("Servidor"),
        content=ft.Column([
            ft.Text(
                "Elige el servidor al que se conectará esta app.",
                size=12, color=ft.Colors.GREY,
            ),
            ft.Row([
                ft.FilledTonalButton(
                    "Local", icon=ft.Icons.COMPUTER,
                    on_click=lambda _: set_url(local_url),
                    expand=True,
                ),
                ft.FilledTonalButton(
                    "Producción", icon=ft.Icons.CLOUD,
                    on_click=lambda _: set_url(production_url),
                    expand=True,
                ),
            ], spacing=8),
            url_field,
            message,
            ft.Text(
                "Local: http://localhost:8080 · Producción: tu dominio HTTPS. "
                "También puedes escribir otra IP o dominio.",
                size=11, color=ft.Colors.GREY,
            ),
        ], tight=True, width=dialog_width(page), scroll=ft.ScrollMode.AUTO),
        actions=[
            ft.TextButton("Cancelar", on_click=lambda _: close_dlg(page, dialog)),
            ft.FilledButton("Guardar y cambiar", on_click=save),
        ],
    )
    open_dlg(page, dialog)
