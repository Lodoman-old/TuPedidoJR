import flet as ft
from mobile.api import api, ApiError
from mobile.utils import close_dlg, open_dlg, snack, dialog_width

ROLE_LABELS = {
    "owner": "Dueño",
    "manager": "Encargado",
    "staff": "Personal",
    "cashier": "Cajero",
    "kitchen": "Cocina",
}


def restaurant_team_view(page: ft.Page, rid: str):
    list_view = ft.ListView(spacing=8, expand=True, padding=10)
    loading = ft.ProgressBar(visible=False)
    error = ft.Text("", color=ft.Colors.RED)

    async def load():
        loading.visible = True
        page.update()
        try:
            members = await api.list_restaurant_team(rid)
            list_view.controls.clear()
            for member in members:
                list_view.controls.append(_member_card(page, rid, member, load))
        except ApiError as ex:
            error.value = ex.detail
        finally:
            loading.visible = False
            page.update()

    def open_add(e):
        name = ft.TextField(label="Nombre")
        email = ft.TextField(label="Correo", keyboard_type=ft.KeyboardType.EMAIL)
        password = ft.TextField(label="Contraseña temporal", password=True, can_reveal_password=True)
        role = ft.Dropdown(
            label="Rol",
            value="staff",
            options=[
                ft.dropdown.Option(key="manager", text="Encargado"),
                ft.dropdown.Option(key="staff", text="Personal"),
                ft.dropdown.Option(key="cashier", text="Cajero"),
                ft.dropdown.Option(key="kitchen", text="Cocina"),
            ],
        )
        msg = ft.Text("", size=11, color=ft.Colors.RED)
        saving = ft.ProgressBar(visible=False)

        async def save(e):
            if not name.value or not email.value or not password.value:
                msg.value = "Completa nombre, correo y contraseña"
                page.update()
                return
            saving.visible = True
            msg.value = ""
            page.update()
            try:
                await api.add_restaurant_team_member(
                    rid, name.value.strip(), email.value.strip(),
                    password.value, role.value or "staff",
                )
                close_dlg(page, dlg)
                snack(page, "Usuario agregado")
                await load()
            except ApiError as ex:
                msg.value = ex.detail
            finally:
                saving.visible = False
                page.update()

        dlg = ft.AlertDialog(
            title=ft.Text("Agregar usuario"),
            content=ft.Column([name, email, password, role, msg, saving], tight=True, width=dialog_width(page)),
            actions=[
                ft.TextButton("Cancelar", on_click=lambda _: close_dlg(page, dlg)),
                ft.FilledButton("Crear usuario", on_click=save),
            ],
        )
        open_dlg(page, dlg)

    async def remove(member):
        try:
            await api.remove_restaurant_team_member(rid, member["id"])
            snack(page, "Acceso eliminado")
            await load()
        except ApiError as ex:
            snack(page, ex.detail, ft.Colors.RED)

    page.run_task(load)

    return ft.View(
        route=f"/restaurant-team/{rid}",
        controls=[
            ft.AppBar(
                title=ft.Text("Equipo del restaurante"),
                leading=ft.IconButton(
                    ft.Icons.ARROW_BACK,
                    on_click=lambda _: page.run_task(page.push_route, f"/restaurant/{rid}"),
                ),
            ),
            ft.SafeArea(ft.Column([
                ft.Container(
                    ft.FilledButton("+ Agregar usuario", icon=ft.Icons.PERSON_ADD, on_click=open_add),
                    padding=10,
                ),
                error, loading, list_view,
            ], expand=True)),
        ],
    )


def _member_card(page: ft.Page, rid: str, member: dict, reload_cb):
    is_owner = member.get("role") == "owner"
    actions = []
    if not is_owner:
        async def remove(e):
            try:
                await api.remove_restaurant_team_member(rid, member["id"])
                await reload_cb()
            except Exception as ex:
                snack(page, str(ex), ft.Colors.RED)

        actions.append(ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_size=18, on_click=lambda e: page.run_task(remove, e)))

    return ft.Container(
        content=ft.Row([
            ft.Column([
                ft.Text(member.get("name") or member.get("email"), weight=ft.FontWeight.BOLD),
                ft.Text(member.get("email") or "", size=12, color=ft.Colors.GREY),
                ft.Text(ROLE_LABELS.get(member.get("role"), member.get("role")), size=12, color=ft.Colors.BLUE),
            ], expand=True, spacing=1),
            *actions,
        ]),
        padding=10, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH, border_radius=10,
    )
