import asyncio
import sys
import traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flet as ft
from mobile.api import api
from mobile.config import get_device_location, get_server_url, save_server_url
from mobile import secure_auth, background_location
from mobile.screens.login import login_view, register_view
from mobile.cart_sync import hydrate_cart
from mobile.screens.restaurant_detail import cart
from mobile.screens.restaurants import restaurants_view
from mobile.screens.restaurant_detail import restaurant_detail_view
from mobile.screens.cart import cart_view
from mobile.screens.orders import orders_view
from mobile.screens.order_detail import order_detail_view
from mobile.screens.delivery import delivery_hub_view, deliver_location_view, delivery_track_view
from mobile.screens.payment import payment_view
from mobile.screens.profile import profile_view
from mobile.push_utils import watch_device_token
from mobile.screens.restaurant_orders import restaurant_orders_view
from mobile.screens.restaurant_earnings import restaurant_earnings_view
from mobile.screens.restaurant_team import restaurant_team_view
from mobile.screens.restaurant_profile import restaurant_profile_view
from mobile.utils import report_error


MAIN_ROUTES = {"/restaurants", "/orders", "/profile", "/delivery"}
_is_dp = False
_location_task: asyncio.Task | None = None


async def _location_reporter():
    """Send the native device location while the courier app is open."""
    while api.token:
        loc = get_device_location()
        if loc:
            try:
                await api.update_location(
                    float(loc["lat"]),
                    float(loc["lng"]),
                    float(loc["speed_kmh"]) if loc.get("speed_kmh") is not None else None,
                )
            except Exception:
                pass
        await asyncio.sleep(15)


def _ensure_location_reporter():
    global _location_task
    if _location_task is None or _location_task.done():
        _location_task = asyncio.create_task(_location_reporter())


def _nav_bar(page: ft.Page):
    if _is_dp:
        idx_map = {"/profile": 0, "/delivery": 1}
        routes = ["/profile", "/delivery"]
        nb = ft.NavigationBar(
            selected_index=idx_map.get(page.route, 0),
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.PERSON, label="Perfil"),
                ft.NavigationBarDestination(icon=ft.Icons.PEDAL_BIKE, label="Repartidor"),
            ],
            on_change=lambda e: page.run_task(page.push_route, routes[e.control.selected_index]),
        )
    else:
        idx_map = {"/restaurants": 0, "/orders": 1, "/profile": 2, "/delivery": 3}
        routes = ["/restaurants", "/orders", "/profile", "/delivery"]
        nb = ft.NavigationBar(
            selected_index=idx_map.get(page.route, 0),
            destinations=[
                ft.NavigationBarDestination(icon=ft.Icons.STORE, label="Restaurantes"),
                ft.NavigationBarDestination(icon=ft.Icons.RECEIPT, label="Pedidos"),
                ft.NavigationBarDestination(icon=ft.Icons.PERSON, label="Perfil"),
                ft.NavigationBarDestination(icon=ft.Icons.PEDAL_BIKE, label="Repartidor"),
            ],
            on_change=lambda e: page.run_task(page.push_route, routes[e.control.selected_index]),
        )
    return nb


async def main(page: ft.Page):
    page.title = "TuPedidoJR."
    page.theme_mode = ft.ThemeMode.LIGHT
    # Persistir la URL efectiva para que la capa nativa (FCM) sepa a qué servidor pedir la configuración.
    save_server_url(get_server_url())
    page.theme = ft.Theme(color_scheme=ft.ColorScheme(
        primary="#1B2F6B",
        on_primary="#FFFFFF",
        primary_container="#DCE4F7",
        on_primary_container="#0B1A45",
        secondary="#F58220",
        on_secondary="#FFFFFF",
        secondary_container="#FFE6D2",
        on_secondary_container="#5A2A00",
        surface="#FFFFFF",
        on_surface="#1B2430",
        surface_container_high="#F2F5FB",
    ))
    page.run_task(watch_device_token)

    async def route_change(e):
        troute = page.route
        page.views.clear()
        try:
            await _build_route(troute)
        except Exception as ex:  # noqa: BLE001
            print("Error abriendo", troute, repr(ex), flush=True)
            page.run_task(report_error, page, f"{type(ex).__name__}: {ex}", traceback.format_exc())
            page.views.clear()
            page.views.append(ft.View(
                route=troute,
                controls=[
                    ft.AppBar(title=ft.Text("TuPedidoJR")),
                    ft.SafeArea(ft.Column([
                        ft.Text("No se pudo abrir esta pantalla", size=16, weight=ft.FontWeight.BOLD),
                        ft.Text(str(ex), size=12, color=ft.Colors.RED, selectable=True),
                    ], spacing=8, padding=16, scroll=ft.ScrollMode.AUTO)),
                ],
            ))
        page.update()

    async def _build_route(troute):
        if troute == "/login":
            page.views.append(login_view(page))
        elif troute == "/register":
            page.views.append(register_view(page))
        elif not api.token:
            page.views.append(login_view(page))
        elif troute == "/restaurants":
            v = restaurants_view(page)
            v.navigation_bar = _nav_bar(page)
            page.views.append(v)
        elif troute.startswith("/restaurant/"):
            rid = troute.split("/restaurant/")[1].split("/")[0]
            if "/cart/" in troute:
                page.views.append(cart_view(page, rid))
            else:
                page.views.append(restaurant_detail_view(page, rid))
        elif troute.startswith("/restaurant-orders/"):
            rid = troute.split("/restaurant-orders/")[1]
            page.views.append(restaurant_orders_view(page, rid))
        elif troute.startswith("/restaurant-earnings/"):
            rid = troute.split("/restaurant-earnings/")[1]
            page.views.append(restaurant_earnings_view(page, rid))
        elif troute.startswith("/restaurant-team/"):
            rid = troute.split("/restaurant-team/")[1]
            page.views.append(restaurant_team_view(page, rid))
        elif troute.startswith("/restaurant-profile/"):
            rid = troute.split("/restaurant-profile/")[1]
            page.views.append(restaurant_profile_view(page, rid))
        elif troute.startswith("/cart/"):
            rid = troute.split("/cart/")[1]
            page.views.append(cart_view(page, rid))
        elif troute == "/orders":
            v = orders_view(page)
            v.navigation_bar = _nav_bar(page)
            page.views.append(v)
        elif troute.startswith("/payment/"):
            oid = troute.split("/payment/")[1]
            page.views.append(payment_view(page, oid))
        elif troute.startswith("/order/"):
            oid = troute.split("/order/")[1]
            page.views.append(order_detail_view(page, oid))
        elif troute == "/profile":
            v = profile_view(page)
            v.navigation_bar = _nav_bar(page)
            page.views.append(v)
        elif troute == "/delivery":
            global _is_dp
            try:
                await api.get_delivery_profile()
                _is_dp = True
            except Exception:
                _is_dp = False
            if _is_dp:
                _ensure_location_reporter()
            v = delivery_hub_view(page, _is_dp)
            v.navigation_bar = _nav_bar(page)
            page.views.append(v)
        elif troute == "/delivery/location":
            page.views.append(deliver_location_view(page))
        elif troute.startswith("/delivery/track/"):
            oid = troute.split("/delivery/track/")[1]
            page.views.append(delivery_track_view(page, oid))
        else:
            page.views.append(login_view(page))

    async def view_pop(e):
        page.views.pop()
        top = page.views[-1] if page.views else None
        if top:
            await page.push_route(top.route)
        else:
            await page.push_route("/restaurants")

    page.on_route_change = route_change
    page.on_view_pop = view_pop

    await secure_auth.init_services(page)

    async def go_home():
        global _is_dp
        await hydrate_cart(cart)
        try:
            dp_profile = await api.get_delivery_profile()
            _is_dp = True
            background_location.configure_from_profile(dp_profile)
            _ensure_location_reporter()
            await page.push_route("/delivery")
        except Exception:
            _is_dp = False
            is_superuser = False
            try:
                me = await api.me()
                is_superuser = bool(me.get("is_superuser"))
            except Exception:
                pass
            if not is_superuser:
                try:
                    mine = await api.get_my_restaurant()
                    if mine and mine.get("id"):
                        await page.push_route(f"/restaurant/{mine['id']}")
                        return
                except Exception:
                    pass
            await page.push_route("/restaurants")

    if api.token:
        await go_home()
        return

    session = await secure_auth.load_session()
    if session.get("token") and session.get("biometric"):
        unlocked = await secure_auth.authenticate(
            "Usa tu huella o rostro para entrar a TuPedidoJR"
        )
        if unlocked:
            api.set_token(session["token"])
            try:
                await api.get_profile()
            except Exception:
                api.clear_token()
                await secure_auth.clear_session()
            else:
                await go_home()
                return

    await page.push_route("/login")


if __name__ == "__main__":
    import os
    assets_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets"))
    ft.run(main, assets_dir=assets_path)