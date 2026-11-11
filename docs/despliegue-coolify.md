# Despliegue en VPS con Coolify

Esta guía deja TuPedidoJR listo para una prueba ligera en producción antes de abrirlo al público.

## 1. Requisitos

- VPS con Docker y Coolify instalado.
- Dominio o subdominio, por ejemplo `beta.tudominio.com`.
- DNS del dominio apuntando al VPS.
- Repositorio Git con este proyecto (GitHub, GitLab o Gitea).

## 2. Archivos que se usan

- `docker-compose.prod.yml`: servicios de base de datos y backend.
- `backend/Dockerfile`: imagen de producción.
- `backend/docker-entrypoint.sh`: aplica migraciones y arranca la app.
- `.env.production.example`: variables de ejemplo.
- `backend/scripts/create_admin.py`: crea el primer administrador sin borrar datos.

## 3. Crear el repositorio y subirlo

```bash
git init -b main
git add .
git commit -m "Preparar despliegue inicial"
git remote add origin git@github.com:TU_USUARIO/TuPedidoJR.git
git push -u origin main
```

No se suben `backend/.env`, tiles, uploads, APK ni builds móviles.

## 3.1 Aislamiento entre proyectos

Este VPS puede tener otros proyectos. Para que TuPedidoJR no se mezcle:

- El compose usa un nombre propio de proyecto:

```yaml
name: tupedidojr
```

- Los volúmenes tienen nombres exclusivos:

```text
tupedidojr_pgdata
tupedidojr_uploads
tupedidojr_tiles
tupedidojr_downloads
```

- La base de datos no publica puertos al host; solo el backend la alcanza dentro de la red `tupedidojr_default`.
- No reutilices variables, volúmenes ni contenedores de otros proyectos.

### En Coolify

Crea un **Team** exclusivo para TuPedidoJR:

1. Selector de equipo arriba a la izquierda.
2. **Create Team** → `TuPedidoJR`.
3. Invita solo al usuario que debe administrar este proyecto.
4. Dentro de ese team crea el proyecto `TuPedidoJR`.

Así, en la interfaz de Coolify, ese usuario no ve los demás proyectos.

### En GitHub

- Repositorio público: no necesitas GitHub App ni cuenta adicional. Usa **Public repository** o el compose pegado.
- Repositorio privado: usa una **Deploy Key** o una **GitHub App instalada solo en `TuPedidoJR`**. No reutilices una cuenta compartida con otros proyectos.
- Si quieres una cuenta dedicada, crea un usuario máquina (por ejemplo `tupedidojr-bot`) y dale acceso solo a este repositorio.

> Los equipos de Coolify separan la interfaz y los permisos. Para aislamiento total a nivel de sistema operativo harían falta VPS o instancias separadas.

## 4. Crear el recurso en Coolify

1. Entra a Coolify.
2. Crea un proyecto y un entorno, por ejemplo `produccion`.
3. Agrega un recurso **Docker Compose**.
4. Conecta el repositorio y selecciona la rama `main`.
5. Archivo Compose: `docker-compose.prod.yml`.
6. Directorio base: la raíz del repositorio.
7. Configura las variables de entorno (sección 5).
8. Asigna el dominio al servicio `backend` en el puerto `8000`.
9. Activa HTTPS.

## 5. Variables de entorno

Copia los valores de `.env.production.example` al panel de Coolify. Como mínimo:

```text
SECRET_KEY
POSTGRES_USER
POSTGRES_PASSWORD
POSTGRES_DB
APP_URL
CORS_ORIGINS
ALLOWED_HOSTS
NOINDEX=true
```

Opcional para notificaciones push:

```text
PUSH_ENABLED=true
FCM_SERVICE_ACCOUNT_JSON=<service account minificada>
PUSH_ANDROID_CONFIG_JSON=<configuración Android>
PUSH_WEB_CONFIG_JSON=<configuración web>
PUSH_VAPID_KEY=<VAPID>
```

Genera `SECRET_KEY` con:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Para `POSTGRES_PASSWORD` usa una contraseña URL-safe (letras, números, `-` y `_`) para que no rompa la cadena de conexión, por ejemplo:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Ejemplo:

```text
APP_URL=https://beta.tudominio.com
CORS_ORIGINS=https://beta.tudominio.com
ALLOWED_HOSTS=beta.tudominio.com,localhost,127.0.0.1
NOINDEX=true
DEBUG=false
```

`NOINDEX=true` evita que buscadores indexen la beta.

## 6. Desplegar

1. Pulsa **Deploy** en Coolify.
2. Espera a que la base de datos esté saludable.
3. El backend ejecuta automáticamente:

```bash
alembic upgrade head
```

4. Verifica:

```text
https://beta.tudominio.com/health
```

Debe responder:

```json
{"status":"ok","app":"TuPedidoJR"}
```

## 7. Crear el administrador

En la terminal del contenedor `backend` de Coolify, o con `docker exec`:

```bash
ADMIN_EMAIL=admin@tudominio.com \
ADMIN_PASSWORD='una-clave-larga-y-segura' \
ADMIN_NAME='Administrador' \
python scripts/create_admin.py
```

Después entra a:

```text
https://beta.tudominio.com/web/login
```

y configura en el panel de administración:

- `/web/admin/settings`
  - URL pública: `https://beta.tudominio.com`
  - Comisión
  - WhatsApp de soporte
  - Correo SMTP
- `/web/admin/restaurants`
  - Aprueba los restaurantes de prueba.

No ejecutes `scripts/seed.py` en producción: borra datos y crea cuentas demo.

## 8. Tiles del mapa

La app usa tiles locales y cae a Esri si no existen.

El volumen `tiles` queda montado en:

```text
/app/static/tiles
```

Para subir los tiles locales:

```bash
# Desde tu computadora al VPS
rsync -av --progress backend/static/tiles/ usuario@vps:/opt/tupedidojr-tiles/

# En el VPS, copiar al contenedor (usa el nombre real del contenedor)
docker cp /opt/tupedidojr-tiles/. NOMBRE_CONTENEDOR:/app/static/tiles/
```

Mientras no subas tiles, el mapa funciona con Esri.

## 9. APK para clientes

El volumen `downloads` queda montado en:

```text
/app/static/downloads
```

Sube el APK:

```bash
# Desde tu computadora al VPS
scp backend/static/downloads/TuPedidoJR.apk usuario@vps:/opt/TuPedidoJR.apk

# En el VPS
docker cp /opt/TuPedidoJR.apk NOMBRE_CONTENEDOR:/app/static/downloads/TuPedidoJR.apk
```

La descarga queda en:

```text
https://beta.tudominio.com/static/downloads/TuPedidoJR.apk
```

### APK apuntando a producción

La app trae un selector de servidor en el login y en el perfil. Puedes cambiar entre:

- **Local**: `mobile/server_local.txt`
- **Producción**: `mobile/server_production.txt`
- URL manual.

Antes de compilar el APK de producción, cambia:

```text
mobile/server_default.txt
mobile/server_production.txt
```

a:

```text
https://beta.tudominio.com
```

Luego recompila el APK. En una instalación existente, el archivo `server.json` del teléfono puede conservar la URL anterior; usa **Cambiar servidor** en el login o borra los datos de la app.

## 10. Respaldos

Respaldo manual de PostgreSQL:

```bash
docker exec NOMBRE_DB pg_dump -U tupedido -d tupedidojr -Fc \
  > tupedidojr-$(date +%Y%m%d-%H%M).dump
```

Recomendado en Coolify:

- Programar un respaldo diario.
- Guardar los respaldos fuera del VPS.
- Respaldar también los volúmenes `uploads` y `downloads`.

## 11. Prueba limpia en producción

Para validar desde cero, **no restaures la base local**. Usa una base nueva y:

1. Crea el administrador con `create_admin.py`.
2. Entra a `/web/register-restaurant` y registra un restaurante de prueba.
3. Apruébalo en `/web/admin/restaurants`.
4. Crea un cliente desde `/web/register` o desde la app.
5. Crea un repartidor desde la app.
6. Prueba:
   - Pedido a domicilio con efectivo y transferencia.
   - Pedido para recoger.
   - Pedido programado.
   - Cambio de estatus por restaurante y repartidor.
   - Calificación de restaurante y repartidor.
   - Ganancias y liquidaciones.

Así los saldos y deudas empiezan en cero.

## 12. Notas importantes

- **Un solo worker:** la app usa WebSockets y estado en memoria. No escales a varios workers/contenedores sin mover ese estado a Redis.
- **HTTPS obligatorio:** el GPS del navegador solo funciona en HTTPS fuera de localhost.
- **FCM/push:** ya está implementado. Sigue [docs/fcm.md](fcm.md) para crear el proyecto de Firebase y cargar las credenciales en `/web/admin/push`.
- **Mercado Pago:** déjalo vacío hasta tener credenciales; efectivo y transferencia funcionan sin ello.
- **OSRM:** si no configuras `OSRM_URL` en ajustes, se usa distancia lineal. Es suficiente para la prueba inicial.
- **Correo:** configura SMTP en `/web/admin/settings` para bienvenida, manuales y recuperación de contraseña.

## 13. Actualizaciones

Cada `git push` a `main` puede redeployar en Coolify. Las migraciones se aplican solas al arrancar.

Antes de actualizar:

1. Haz respaldo de la base.
2. Revisa que las migraciones nuevas sean compatibles.
3. Despliega.
4. Verifica `/health` y los flujos principales.
