import flet as ft
from mobile.api import api, ApiError
from mobile import secure_auth, background_location


def restaurants_view(page: ft.Page):
    search = ft.TextField(hint_text="Buscar restaurante, giro o platillo...", prefix_icon=ft.Icons.SEARCH)
    filter_open = ft.Switch(label="Abiertos", value=False)
    filter_sort = ft.Dropdown(
        options=[
            ft.dropdown.Option(key="", text="Más cercanos"),
            ft.dropdown.Option(key="rating", text="Mejor calificados"),
            ft.dropdown.Option(key="fee", text="Menor envío"),
        ],
        value="",
        width=200,
        dense=True,
        text_size=12,
    )
    loading = ft.ProgressBar(visible=False)
    list_view = ft.ListView(spacing=8, padding=10, expand=True)
    error_text = ft.Text("", color=ft.Colors.RED)

    async def _guard_role():
        try:
            me = await api.me()
            if me.get("is_superuser"):
                return
            mine = await api.get_my_restaurant()
            if mine and mine.get("id"):
                await page.push_route(f"/restaurant/{mine['id']}")
        except Exception:
            pass

    page.run_task(_guard_role)

    async def load():
        loading.visible = True
        error_text.value = ""
        page.update()
        try:
            q = search.value.strip() if search.value else None
            filters = {}
            if filter_open.value:
                filters["open_now"] = "true"
            if filter_sort.value:
                filters["sort"] = filter_sort.value
            data = await api.list_restaurants(q=q, filters=filters)
            list_view.controls.clear()
            for r in data:
                list_view.controls.append(_restaurant_card(page, r))
            if not data:
                list_view.controls.append(ft.Text("Sin restaurantes disponibles", color=ft.Colors.GREY, text_align=ft.TextAlign.CENTER))
        except ApiError as ex:
            error_text.value = ex.detail
        finally:
            loading.visible = False
            page.update()

    async def on_search(e):
        q = search.value.strip() if search.value else ""
        if len(q) >= 2 or len(q) == 0:
            await load()

    filter_open.on_change = lambda e: page.run_task(load)
    filter_sort.on_change = lambda e: page.run_task(load)

    async def logout(e):
        api.clear_token()
        background_location.set_enabled(False)
        await secure_auth.clear_session()
        await page.push_route("/login")

    search.on_change = on_search

    page.on_resume = lambda: None

    appbar = ft.AppBar(
        title=ft.Image(src="logo.png", height=28),
        actions=[
            ft.IconButton(ft.Icons.PERSON, on_click=lambda _: page.run_task(page.push_route, "/profile")),
            ft.IconButton(ft.Icons.LOGOUT, on_click=lambda e: page.run_task(logout, e)),
        ],
        center_title=True,
        toolbar_height=48,
    )

    page.run_task(load)

    content = ft.Column([
        search,
        ft.Row([
            filter_sort,
            filter_open,
        ], spacing=10, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        error_text, loading, list_view,
    ], expand=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    return ft.View(
        route="/restaurants",
        controls=[appbar, ft.SafeArea(content)],
    )


def _restaurant_card(page: ft.Page, r: dict):
    dist = f" · {r['distance_m']:.0f}m" if r.get("distance_m") else ""
    logo = r.get("logo_url")
    logo_img = ft.Image(src=f"{api.api_url}{logo}", width=50, height=50, border_radius=8) if logo else ft.Icon(ft.Icons.STORE, size=40, color=ft.Colors.GREY)
    return ft.Container(
        content=ft.Row([
            logo_img,
            ft.Column([
                ft.Text(r["name"], size=18, weight=ft.FontWeight.BOLD),
                ft.Row([
                    ft.Icon(ft.Icons.STAR, size=14, color=ft.Colors.AMBER),
                    ft.Text(str(r["rating"])),
                    ft.Text(dist, color=ft.Colors.GREY),
                ]),
                ft.Text(f"Envío: ${float(r['delivery_fee']):.2f}", size=13, color=ft.Colors.GREY),
                *([ft.Text(r["cuisine"], size=12, color=ft.Colors.BLUE)] if r.get("cuisine") else []),
                *([ft.Text("Entrega propia", size=12, color=ft.Colors.TEAL)] if r.get("delivery_mode") == "own" else []),
                *([ft.Text("Recoger en restaurante", size=12, color=ft.Colors.BLUE)] if r.get("pickup_enabled") else []),
                *([ft.Text("Cerrado ahora", size=12, color=ft.Colors.RED)] if r.get("is_open_now") is False else []),
            ], expand=True),
        ], spacing=12),
        padding=12,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH,
        border_radius=12,
        ink=True,
        on_click=lambda _, rid=r["id"]: page.run_task(page.push_route, f"/restaurant/{rid}"),
    )
