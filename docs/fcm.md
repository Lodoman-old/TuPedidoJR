# Configurar FCM (notificaciones push)

TuPedidoJR ya tiene el código de FCM. Solo falta crear el proyecto en Firebase y pegar las credenciales en el panel de administración.

## Requisitos

- Cuenta de Google.
- Acceso de superadministrador a `/web/admin/push`.
- Dominio con HTTPS.
- APK reciente instalada.

## 1. Crear el proyecto en Firebase

1. Entra a https://console.firebase.google.com/
2. **Agregar proyecto**.
3. Nombre sugerido: `TuPedidoJR`.
4. Puedes desactivar Google Analytics para la prueba inicial.
5. Espera a que se cree.

## 2. Agregar la app Android

1. En el proyecto, toca el ícono de Android.
2. Paquete: `com.tupedidojr.tupedidojr`
3. Nombre: `TuPedidoJR`
4. Descarga `google-services.json`.

No necesitas agregar ese archivo al APK: la app descarga la configuración desde el backend. El archivo sirve para sacar estos valores:

```json
{
  "project_id": "project_info.project_id",
  "mobilesdk_app_id": "client[0].client_info.mobilesdk_app_id",
  "api_key": "client[0].api_key[0].current_key",
  "gcm_defaultSenderId": "project_info.project_number"
}
```

Opcionalmente agrega:

```json
"storage_bucket": "project_info.storage_bucket"
```

## 3. Agregar la app web

1. En Firebase, toca el ícono web `</>`.
2. Nombre: `TuPedidoJR Web`.
3. Copia el objeto `firebaseConfig`:

```json
{
  "apiKey": "...",
  "authDomain": "...",
  "projectId": "...",
  "storageBucket": "...",
  "messagingSenderId": "...",
  "appId": "..."
}
```

Ese objeto se pega en **Configuración web** del panel de push.

## 4. Service account privada

1. Firebase → ⚙️ **Configuración del proyecto**.
2. Pestaña **Cuentas de servicio**.
3. **Generar nueva clave privada**.
4. Se descarga un JSON.

Ese JSON completo se pega en **Service account JSON**.

> Es privada. No la subas a Git ni la compartas. El backend la guarda en la base de datos.

## 5. VAPID key para web

1. Firebase → **Cloud Messaging**.
2. En **Certificados push web**, genera un par de claves.
3. Copia la clave pública, empieza con `B`.

Se pega en **VAPID key**.

## 6. Configurar en TuPedidoJR

Entra a:

```text
https://TU_DOMINIO/web/admin/push
```

Pega:

- Service account JSON.
- Configuración web.
- Configuración Android.
- VAPID key.

Activa **Notificaciones push** y guarda.

## 7. Probar

En la misma pantalla:

1. Revisa el contador de tokens.
2. Usa **Enviar prueba** a tu usuario.
3. Debe llegar al teléfono o a la web.

Si el contador está en 0, todavía no hay dispositivos registrados.

## 8. APK

1. Instala la APK más reciente desde `/web/app`.
2. Inicia sesión.
3. Acepta el permiso de notificaciones.
4. Espera unos segundos o vuelve a abrir la app.

La app:

- Descarga `/api/v1/push/config`.
- Inicializa Firebase con la configuración Android.
- Obtiene el token FCM.
- Lo registra en `/api/v1/push/tokens`.

El registro se reintenta al iniciar sesión y cada 20 segundos si el token cambia o llega tarde.

## 9. Web y iPhone

En el perfil web:

1. **Activar notificaciones**.
2. Acepta el permiso del navegador.

Requisitos:

- HTTPS.
- En iPhone, la web debe estar instalada como PWA en la pantalla de inicio.
- El service worker se registra en `/web/firebase-messaging-sw.js`.

## 10. Qué notificaciones se envían

- Cambios de estatus del pedido al cliente.
- Pedido nuevo al dueño y al equipo del restaurante.
- Mandado nuevo a los mandaderos.
- Cambios de estatus del mandado al cliente.
- Prueba manual desde el panel.

## 10. Producción en Coolify

Para que producción quede configurada sin volver a pegar nada en el panel, agrega estas variables al servicio `backend` en Coolify:

```text
PUSH_ENABLED=true
FCM_SERVICE_ACCOUNT_JSON=<service account minificada en una línea>
PUSH_ANDROID_CONFIG_JSON={"project_id":"tupedidojr-30f28","mobilesdk_app_id":"1:88387960123:android:99ae008757264de1c64b1e","api_key":"AIzaSyBqdmulTYLvfsc61OSU_YJuDNrxWHqZm3s","gcm_defaultSenderId":"88387960123","storage_bucket":"tupedidojr-30f28.firebasestorage.app"}
```

Opcional para web:

```text
PUSH_WEB_CONFIG_JSON=<firebaseConfig web minificado>
PUSH_VAPID_KEY=<clave pública VAPID>
```

Para minificar la service account y copiarla al portapapeles en Windows:

```powershell
Get-Content -Raw archivo-service-account.json |
  ConvertFrom-Json |
  ConvertTo-Json -Compress |
  Set-Clipboard
```

Después pégala en `FCM_SERVICE_ACCOUNT_JSON` de Coolify.

El backend aplica estos valores al arrancar **solo si todavía no existen** en la base. No pisa cambios hechos después desde `/web/admin/push`.

## 11. Problemas comunes

### El contador de tokens sigue en 0

- `PUSH_ENABLED` debe estar activo.
- La service account debe ser del mismo proyecto que la app Android.
- El paquete Android debe ser exactamente `com.tupedidojr.tupedidojr`.
- La APK debe apuntar al servidor correcto.
- Debe aceptarse el permiso de notificaciones.
- Prueba cerrar y abrir la app; el token se reintenta.

### La web no pide permiso

- Debe ser HTTPS.
- El service worker debe cargar sin errores.
- La configuración web y la VAPID deben estar guardadas.
- En iPhone, instala la PWA primero.

### Llega a unos dispositivos y a otros no

- Revisa el token inactivo en la base.
- Desinstalar/reinstalar la app genera un token nuevo.
- Algunos Android requieren desactivar la optimización de batería para la app.

### Error de service account

- Debe incluir `client_email`, `private_key` y `project_id`.
- Debe ser del proyecto correcto.
- No debe tener saltos de línea rotos al pegarla.

## Seguridad

- La service account es privada; solo el superadministrador la carga.
- La configuración web y Android son públicas por diseño de Firebase.
- El token FCM se guarda asociado al usuario en la tabla `push_tokens`.
- FCM es gratuito para este uso.
