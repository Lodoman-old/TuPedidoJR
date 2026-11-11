# TuPedidoJR

Plataforma de pedidos, restaurantes, repartidores, mandados y lealtad.

## Desarrollo local

```bash
docker compose up --build
```

La app queda en `http://localhost:8080`.

## Producción con Coolify

Consulta [docs/despliegue-coolify.md](docs/despliegue-coolify.md).

Resumen:

- `docker-compose.prod.yml` para Coolify.
- Variables en `.env.production.example`.
- El backend aplica migraciones al arrancar.
- Crea el administrador con `backend/scripts/create_admin.py`.

## Estructura

- `backend/`: API FastAPI, panel web, WebSockets y base de datos.
- `mobile/`: app Flet/Flutter.
- `docs/`: documentación de operación y despliegue.
