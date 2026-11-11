import flet as ft
from mobile.api import api, ApiError
from mobile import secure_auth
from mobile.cart_sync import hydrate_cart
from mobile.push_utils import register_device_token
from mobile.screens.restaurant_detail import cart


def _build_logo(size: int = 80):
    return ft.Image(src=f"{api.api_url}/static/logo.png", height=size)


def login_view(page: ft.Page):
    email = ft.TextField(label="Correo electrónico", keyboard_type=ft.KeyboardType.EMAIL, autofocus=True)
    password = ft.TextField(label="Contraseña", password=True, can_reveal_password=True)
    server_url = ft.TextField(
        label="Servidor",
        value=api.api_url,
        hint_text="http://192.168.1.10:8080",
        keyboard_type=ft.KeyboardType.URL,
    )
    error_text = ft.Text("", color=ft.Colors.RED)
    loading = ft.ProgressBar(visible=False)

    async def do_login(e):
        if not email.value or not password.value:
            error_text.value = "Llena todos los campos"
            page.update()
            return
        error_text.value = ""
        loading.visible = True
        page.update()
        try:
            api.set_server_url(server_url.value)
            logo.src = f"{api.api_url}/static/logo.png"
            server_url.value = api.api_url
            resp = await api.login(email.value, password.value)
            api.set_token(resp["access_token"])
            await secure_auth.save_session(resp["access_token"], email.value, "")
            await hydrate_cart(cart)
            page.run_task(register_device_token)
            await page.push_route("/restaurants")
        except ApiError as ex:
            error_text.value = ex.detail
        except Exception:
            error_text.value = "No se pudo conectar al servidor. Revisa la dirección en 'Servidor'."
        finally:
            loading.visible = False
            page.update()

    logo = _build_logo()

    return ft.View(
        route="/login",
        controls=[
            ft.SafeArea(
                ft.Column([
                    ft.Container(height=40),
                    logo,
                    ft.Container(height=10),
                    ft.Text("Inicia sesión", size=16, color=ft.Colors.GREY),
                    ft.Container(height=20),
                    email, password, ft.Container(height=10),
                    error_text, loading,
                    ft.FilledButton("Entrar", on_click=do_login, width=300),
                    ft.TextButton("¿No tienes cuenta? Regístrate", on_click=lambda _: page.run_task(page.push_route, "/register")),
                    ft.TextButton("Registrar mi restaurante", on_click=lambda _: page.launch_url(f"{api.api_url}/web/register-restaurant")),
                    ft.TextButton("Olvidé mi contraseña", on_click=lambda _: page.launch_url(f"{api.api_url}/web/forgot-password")),
                    ft.ExpansionTile(
                        title=ft.Text("Servidor / conexión", size=13, color=ft.Colors.GREY),
                        controls=[
                            server_url,
                            ft.Text(
                                "En el celular usa la IP o dominio del servidor, por ejemplo http://192.168.1.10:8080",
                                size=11, color=ft.Colors.GREY,
                            ),
                        ],
                    ),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)
            )
        ]
    )


def register_view(page: ft.Page):
    name = ft.TextField(label="Nombre", autofocus=True)
    email = ft.TextField(label="Correo electrónico", keyboard_type=ft.KeyboardType.EMAIL)
    phone = ft.TextField(label="Teléfono (opcional)")
    referral = ft.TextField(label="Código de referido (opcional)")
    password = ft.TextField(label="Contraseña", password=True, can_reveal_password=True)
    error_text = ft.Text("", color=ft.Colors.RED)
    loading = ft.ProgressBar(visible=False)

    async def do_register(e):
        if not name.value or not email.value or not password.value:
            error_text.value = "Llena todos los campos obligatorios"
            page.update()
            return
        error_text.value = ""
        loading.visible = True
        page.update()
        try:
            resp = await api.register(name.value, email.value, password.value, phone.value or None, referral.value.strip().upper() or None)
            api.set_token(resp["access_token"])
            await secure_auth.save_session(resp["access_token"], email.value, name.value)
            await hydrate_cart(cart)
            page.run_task(register_device_token)
            await page.push_route("/restaurants")
        except ApiError as ex:
            error_text.value = ex.detail
        finally:
            loading.visible = False
            page.update()

    logo = _build_logo(size=60)

    return ft.View(
        route="/register",
        controls=[
            ft.SafeArea(
                ft.Column([
                    logo,
                    ft.Container(height=10),
                    ft.Text("Crear cuenta", size=24, weight=ft.FontWeight.BOLD),
                    ft.Container(height=10),
                    name, email, phone, password, referral, ft.Container(height=10),
                    error_text, loading,
                    ft.FilledButton("Registrarse", on_click=do_register, width=300),
                    ft.TextButton("¿Ya tienes cuenta? Inicia sesión", on_click=lambda _: page.run_task(page.push_route, "/login")),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)
            )
        ]
    )
