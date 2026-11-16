# Activar Cloudflare en TuPedidoJR

Esta guía sirve para poner TuPedidoJR detrás de Cloudflare **sin afectar otros
sitios** que ya estén en la misma cuenta.

## Regla de oro

No muevas ajustes **de toda la zona** si el dominio también lo usan otros
sitios productivos:

- SSL/TLS mode
- Bot Fight Mode
- Under Attack Mode
- Security Level
- Page Rules / Transform Rules globales

Solo agrega el **registro DNS del nuevo dominio** y reglas **limitadas a ese
hostname**. Si quieres cero riesgo compartido, usa un dominio dedicado para
TuPedidoJR.

## Antes de empezar

El dominio actual es de `sslip.io` y **no se puede usar en Cloudflare** porque
no controlamos esa zona. Necesitas:

- un dominio propio (ej. `tupedidojr.com`), o
- un subdominio de un dominio que ya tengas en Cloudflare.

## Pasos

1. **DNS**
   - Agrega un registro `A` (o `CNAME`) del nuevo dominio apuntando a la IP del
     servidor (`31.97.12.7`).
   - Déjalo primero en **DNS only** (nube gris) y verifica que cargue por HTTPS
     el certificado actual.

2. **SSL/TLS**
   - Cambia a **Full (strict)** para ese hostname (no "Flexible": provoca
     redirecciones infinitas).
   - Activa **Always Use HTTPS**.

3. **Rendimiento**
   - Desactiva **Rocket Loader** y **Auto Minify** para este hostname: pueden
     romper el JavaScript del carrito, el mapa y los paneles.
   - No actives caché agresiva: las páginas ya mandan `Cache-Control: no-store`.

4. **Reglas por hostname (opcional, recomendado)**
   - Rate limit: `60` solicitudes/minuto por IP a `/api/v1/auth/login`.
   - Rate limit: `300` solicitudes/minuto por IP al resto del hostname.
   - No apliques reglas a toda la zona.

5. **En TuPedidoJR**
   - Agrega el nuevo dominio a `ALLOWED_HOSTS` y `CORS_ORIGINS` (variables de
     entorno en Coolify) y redespliega.
   - Actualiza el ajuste `APP_PUBLIC_URL` para que correos y manuales usen el
     dominio nuevo.
   - En **Administrador → Seguridad y bloqueos**, activa
     **"Confiar en Cloudflare (CF-Connecting-IP)"**.
   - Agrega tu IP de oficina a la lista de confianza con el botón
     **"Agregar a confianza"**.

6. **Protege el origen**
   - Restringe el firewall del VPS para aceptar tráfico web solo desde los
     rangos de Cloudflare (https://www.cloudflare.com/ips/). Así nadie puede
     saltarse Cloudflare y falsificar cabeceras.

7. **Activa el proxy (nube naranja)**
   - Cambia el registro a **Proxied**.
   - Verifica en este orden:
     - inicio y landing,
     - login y registro,
     - catálogo y carrito,
     - crear un pedido de prueba,
     - seguimiento en vivo (WebSockets),
     - panel del negocio,
     - panel de administración,
     - descarga de la APK,
     - que la página de seguridad muestre **tu IP real**.

8. **Rollback**
   - Si algo falla, vuelve el registro a **DNS only** (nube gris). El sitio
     sigue funcionando igual que antes, sin tocar los demás dominios.

## La APK

La APK oficial abre la URL configurada en `capacitor/capacitor.config.json`.
Si cambias de dominio:

- mantén el dominio viejo funcionando mientras publicas una APK nueva, o
- reconstruye la APK con el dominio nuevo y avisa a los repartidores.

## Qué NO resuelve Cloudflare

- No impide que alguien copie el catálogo a mano; eso lo corta el bloqueo por
  ráfagas del panel de seguridad.
- El plan gratuito no detiene un DDoS muy grande, pero filtra bots y escaneos
  comunes antes de que lleguen al servidor.
