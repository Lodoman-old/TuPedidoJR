# Diseño técnico: operación de reparto sin repartidores

Estado: **Fase 1 y Fase 2 implementadas en local**. Pendiente de revisión y despliegue.
Fecha: 2026-11-26.

Decisiones finales:

- El cambio a recoger con transferencia ya pagada reembolsa el envío y queda
  pendiente para el siguiente día hábil.
- El envío que entrega el administrador se registra como ingreso de la
  plataforma.
- La bandera `DELIVERY_OPS_V2_ENABLED` está activada solo en local para pruebas.
- Los negocios con reparto propio pueden pedir apoyo de TuPedidoJR y el cargo
  se descuenta de su siguiente corte.
- Los pedidos programados se muestran arriba con color y recordatorio; si el
  negocio intenta preparar perecederos antes de tiempo, se le advierte.

## 1. Objetivo

Evitar pedidos atorados cuando no hay repartidores disponibles, permitir que el
cliente espere o recoja en el negocio, avisar al administrador a tiempo y darle
herramientas para resolver el pedido. También dejar visibles los pedidos
programados y el corte por cierre del negocio.

## 2. Decisiones de negocio acordadas

1. El aviso de "sin repartidores" solo aplica a pedidos con reparto de
   TuPedidoJR (`delivery_mode = "platform"`).
2. Si no hay repartidores, el cliente puede esperar 30 minutos o recoger en el
   negocio.
3. Si espera, el pedido no se prepara hasta que un repartidor lo acepte.
4. A los 15 minutos de estar listo sin repartidor, se avisa al administrador.
5. A los 30 minutos, se avisa al cliente para que elija recoger o cancelar.
6. El administrador puede asignar repartidor, entregar el pedido él mismo,
   cambiar a recoger o cancelar.
7. Los negocios con reparto propio no se afectan. Si se quedan sin repartidor,
   pueden pedir apoyo de TuPedidoJR y el negocio paga la tarifa, descontada de
   su siguiente corte.
8. El reparto de TuPedidoJR opera 24 horas si hay repartidor disponible.
9. A 30 minutos del cierre, el negocio debe aceptar el pedido. Si no responde
   en 10 minutos, se cancela y se avisa al cliente.
10. Los pedidos programados se muestran arriba, con color y fecha/hora. Se
    avisa al negocio 1 hora antes. Se validan contra el horario del negocio.
11. Si el negocio intenta preparar un programado mucho antes, se le advierte
    sobre perecederos y elige aceptar o esperar.
12. Las contraseñas de configuración ya se enmascaran (implementado).

## 3. Alcance por fases

### Fase 1 (antes de producción)

- Aviso de disponibilidad y elección esperar/recoger en el checkout.
- Retención del pedido sin preparar hasta que un repartidor lo acepte.
- Aviso al administrador a los 15 minutos.
- Acciones del administrador: asignar, tomar/entregar, cambiar a recoger,
  cancelar.
- Corte de 30 minutos antes de cerrar y cancelación a los 10 minutos.
- Notificaciones al cliente y al negocio.

### Fase 2

- Pedidos programados arriba, con color, recordatorio de 1 hora y validación de
  horario.
- Aviso de preparación anticipada en perecederos.
- Apoyo de reparto para negocios con reparto propio, con cargo al corte.

### Fase 3

- Turnos y disponibilidad programada de repartidores.
- Pronóstico de cobertura por franja horaria.

## 4. Modelo de datos

### Migración 078 (nueva)

Archivo: `backend/alembic/versions/078_delivery_ops.py`
`down_revision = "077"`

| Columna | Tipo | Default | Uso |
|---|---|---|---|
| `no_courier_hold` | Boolean | false | Pedido retenido porque no había repartidores al crear. |
| `no_courier_notified_at` | DateTime TZ | null | Cuándo se avisó al cliente que puede recoger o cancelar. |
| `no_courier_decision_deadline` | DateTime TZ | null | Límite para que el cliente decida. |
| `courier_alert_at` | DateTime TZ | null | Cuándo se avisó al admin por 15 minutos sin repartidor. |
| `near_closing` | Boolean | false | Pedido dentro de los 30 minutos previos al cierre. |
| `business_confirmation_deadline` | DateTime TZ | null | Límite de 10 minutos para que el negocio acepte. |
| `admin_delivery` | Boolean | false | El administrador tomó el pedido para entregarlo. |
| `admin_delivery_by` | UUID FK users | null | Administrador que tomó el pedido. |

Índices:

- `ix_orders_courier_alert_at`
- `ix_orders_no_courier_decision_deadline`
- `ix_orders_business_confirmation_deadline`

No se agregan estados nuevos. Se reutilizan:

- `requires_courier_approval = true` para ocultar el pedido al negocio.
- `courier_approval_deadline` para el límite de 30 minutos.
- `status = "awaiting_courier"` mientras se busca repartidor.
- `admin_delivery` como bandera, no como estado.

### Configuración nueva

En `backend/app/api/v1/settings.py`, grupo "Envíos" y "Repartidores":

| Llave | Tipo | Default | Uso |
|---|---|---|---|
| `DELIVERY_OPS_V2_ENABLED` | bool | false | Interruptor general del flujo nuevo. |
| `NO_COURIER_WAIT_MIN` | int | 30 | Espera máxima del cliente. |
| `NO_COURIER_DECISION_MIN` | int | 15 | Tiempo para decidir recoger o cancelar. |
| `COURIER_ALERT_MIN` | int | 15 | Minutos listo sin repartidor para avisar al admin. |
| `NEAR_CLOSING_MIN` | int | 30 | Minutos antes del cierre para pedir confirmación. |
| `NEAR_CLOSING_RESPONSE_MIN` | int | 10 | Tiempo del negocio para aceptar. |
| `SCHEDULED_REMINDER_MIN` | int | 60 | Aviso previo de pedido programado. |
| `COURIER_SUPPORT_ENABLED` | bool | false | Permite apoyo de reparto a negocios con reparto propio. |

`DELIVERY_OPS_V2_ENABLED` permite desplegar el código sin cambiar la operación
hasta probarlo.

## 5. Backend

### 5.1 Disponibilidad de repartidores

Nuevo servicio: `backend/app/services/courier_availability.py`

Funciones:

- `available_courier_count(db) -> int`
  - Cuenta `DeliveryPerson.is_available = true`.
  - Descuenta los que ya están en su límite de servicios activos usando
    `app/services/courier_limits.py`.
- `available_couriers(db) -> list[dict]`
  - Devuelve id, nombre, vehículo y servicios activos para el modal del admin.
- `courier_availability_for_order(db, delivery_mode) -> dict`
  - Devuelve `{"available": n, "enabled": delivery_mode == "platform"}`.

### 5.2 Estimación de precio y checkout

Archivo: `backend/app/api/v1/orders.py`

`estimate_price` agrega al response:

```json
{
  "available_couriers": 0,
  "no_courier": true,
  "no_courier_wait_min": 30,
  "no_courier_decision_min": 15,
  "near_closing": false,
  "minutes_to_close": 120,
  "near_closing_min": 30
}
```

`OrderCreate` agrega:

```python
no_courier_action: str | None = Field(default=None, pattern="^(wait|pickup)$")
```

En `create_order`, después de calcular distancia y antes de crear:

```python
if not pickup and restaurant.delivery_mode == "platform":
    available = await available_courier_count(db)
    if available == 0:
        if body.no_courier_action != "wait":
            raise HTTPException(409, "No hay repartidores disponibles. Elige recoger en el negocio.")
        requires_approval = True
        no_courier_hold = True
        courier_deadline = now + wait_min

    minutes_to_close = await minutes_to_close(db, restaurant)
    if minutes_to_close is not None and minutes_to_close <= near_closing_min:
        near_closing = True
        business_deadline = now + response_min
```

Reglas:

- Si `no_courier_action = "pickup"`, el frontend cambia `fulfillment_type` a
  `pickup`; el backend lo valida y no aplica retención.
- Si no hay repartidores y el pedido es a domicilio sin elección explícita, se
  rechaza con 409 para evitar pedidos accidentales.
- La retención usa `requires_courier_approval = true`, por lo que el negocio no
  ve el pedido hasta que un repartidor lo acepte.
- Si además está cerca del cierre, el negocio sí debe verlo para aceptar o
  rechazar, pero no puede prepararlo hasta que haya repartidor.

### 5.3 Horario y cierre

Archivo: `backend/app/services/schedule_service.py`

Agregar:

- `current_shift(schedules, now) -> dict | None`
  - Devuelve `open_at`, `close_at`, `is_overnight` del turno vigente.
  - Considera el turno que empezó ayer.
- `minutes_to_close(db, restaurant, now=None) -> int | None`
  - `None` si no hay horario.
  - Minutos hasta el cierre del turno vigente.
- `schedule_state_at(schedules, target) -> dict`
  - Para validar pedidos programados (Fase 2).

### 5.4 Creación y estados del pedido

- `no_courier_hold = true`:
  - `status = "awaiting_courier"`.
  - `requires_courier_approval = true`.
  - `courier_approval_deadline = now + NO_COURIER_WAIT_MIN`.
  - No se notifica al negocio.
  - Se ofrece a repartidores disponibles; si no hay, queda en la cola.
- Cuando un repartidor acepta:
  - `delivery_person_id = dp.id`.
  - `status = "preparing"`.
  - Se notifica al negocio.
- `near_closing = true`:
  - El pedido se muestra al negocio con badge "Cerca del cierre".
  - El negocio acepta o rechaza.
  - Al aceptar: `near_closing = false`, se limpia el deadline y sigue el flujo.
  - Al rechazar o vencer: se cancela y se notifica al cliente.

### 5.5 Endpoints del negocio

Archivo: `backend/app/api/v1/restaurants.py`

- `GET /restaurants/{id}/orders`
  - Incluir pedidos `near_closing` aunque tengan
    `requires_courier_approval = true` y no tengan repartidor.
- `PATCH /restaurants/{id}/orders/{order_id}/status`
  - Si `near_closing` y el negocio intenta aceptar, permitir solo
    `confirmed` o `preparing`.
  - Limpiar `near_closing` y `business_confirmation_deadline`.
- `POST /restaurants/{id}/orders/{order_id}/reject-near-closing`
  - Cancela con motivo "El negocio no aceptó el pedido cerca del cierre".

### 5.6 Endpoints del administrador

Nuevo router: `backend/app/api/v1/admin_orders.py`

| Método | Ruta | Uso |
|---|---|---|
| GET | `/admin/orders/courier-alerts` | Pedidos sin repartidor que ya requieren atención. |
| POST | `/admin/orders/{id}/assign-courier` | Asignar un repartidor específico. |
| POST | `/admin/orders/{id}/take-delivery` | El admin toma el pedido para entregarlo. |
| POST | `/admin/orders/{id}/status` | Marcar recogido/entregado en reparto propio. |
| POST | `/admin/orders/{id}/switch-to-pickup` | Cambiar a recoger en el negocio. |
| POST | `/admin/orders/{id}/cancel` | Reutiliza la cancelación existente. |

Reglas:

- `assign-courier`:
  - Valida que el repartidor esté activo y disponible.
  - Valida límite de servicios.
  - Asigna `delivery_person_id`.
  - Si el pedido estaba en `awaiting_courier` o `pending`, pasa a `preparing`.
  - Notifica al repartidor y al negocio.
- `take-delivery`:
  - Solo si no tiene repartidor y el pedido no está entregado/cancelado.
  - `admin_delivery = true`, `admin_delivery_by = current_user.id`.
  - `requires_courier_approval = false`.
  - El pedido deja de aparecer a repartidores.
  - El negocio puede prepararlo.
- `status`:
  - Solo para pedidos con `admin_delivery = true`.
  - Permite `picked_up` y `delivered`.
  - Al entregar, si es efectivo, marcar cobrado.
  - No genera pago a repartidor.
- `switch-to-pickup`:
  - Si el pedido no está pagado: cambia `fulfillment_type`, quita envío y
    recalcula total.
  - Si ya está pagado por transferencia: se registra un reembolso pendiente
    del envío y se avisa al cliente que se procesa el siguiente día hábil.
  - No permitido si ya está en reparto o entregado.

### 5.7 Panel del administrador

Archivo: `backend/app/api/v1/admin_dashboard.py`

Agregar al response:

```json
{
  "courier_alerts": [
    {
      "id": "...",
      "short": "ABCD1234",
      "restaurant_name": "...",
      "status": "ready",
      "minutes": 18,
      "total": "250.00",
      "no_courier_hold": true,
      "admin_delivery": false
    }
  ],
  "near_closing_alerts": [...],
  "available_couriers": [...]
}
```

Archivo: `backend/templates/web/dashboard_admin.html`

Nueva tarjeta "Pedidos sin repartidor" con:

- Pedido, negocio, estado, minutos, total.
- Botones:
  - **Asignar** → modal con repartidores disponibles.
  - **Tomar** → confirmación; el admin entregará.
  - **Recogí** / **Entregué** → solo si `admin_delivery`.
  - **Pasar a recoger**.
  - **Cancelar**.

La tarjeta se actualiza cada 30 segundos junto con el dashboard.

### 5.8 Tareas de fondo

Nuevo servicio: `backend/app/services/delivery_ops_service.py`

Loop cada 60 segundos, iniciado en `backend/app/main.py`:

1. **Sin repartidor, 15 minutos listo**
   - Busca pedidos `delivery_mode = "platform"`, sin `delivery_person_id`,
     estado `preparing` o `ready`, con más de `COURIER_ALERT_MIN` minutos.
   - Si `courier_alert_at` es null, envía push/correo al admin y lo marca.
2. **Sin repartidor, 30 minutos**
   - Busca `no_courier_hold = true`, sin repartidor, con
     `courier_approval_deadline <= now`.
   - Envía aviso al cliente, marca `no_courier_notified_at` y fija
     `no_courier_decision_deadline = now + NO_COURIER_DECISION_MIN`.
   - No cancela todavía.
3. **Cliente no decide**
   - Si `no_courier_decision_deadline <= now`, cancela con
     `apply_cancellation` y avisa al cliente.
4. **Cerca del cierre sin respuesta**
   - Si `near_closing = true` y `business_confirmation_deadline <= now`,
     cancela y avisa al cliente.
   - Si el pago fue por transferencia, deja `refund_status = "pending"` y el
     mensaje "reembolso el siguiente día hábil".
5. **Pedidos programados** (Fase 2)
   - Envía recordatorio al negocio `SCHEDULED_REMINDER_MIN` antes.

El loop actual `courier_timeout_service.py` se mantiene para pedidos lejanos
que no son `no_courier_hold`, o se integra al nuevo servicio para no tener dos
loops compitiendo.

Regla obligatoria: `courier_timeout_service._cancel_expired` debe excluir
`no_courier_hold = true`; esos pedidos los maneja `delivery_ops_service` para
avisar al cliente antes de cancelar.

### 5.10 Cola de repartidores

Archivo: `backend/app/api/v1/delivery.py`

La consulta de pedidos disponibles debe excluir `admin_delivery = true`, para
que un pedido tomado por el administrador no se ofrezca a repartidores.

### 5.11 Seguimiento del cliente

Archivo: `backend/app/services/tracking_service.py`

Si `admin_delivery = true` y no hay `delivery_person_id`, el seguimiento debe
mostrar "En reparto por TuPedidoJR" sin ubicación de repartidor, en lugar de
quedarse sin paso de reparto.

### 5.9 Notificaciones

Archivo: `backend/app/services/push_service.py`

Agregar:

- `notify_customer_no_courier(order_id, wait_min)`
  - Push y correo: "No hay repartidor. Puedes esperar o recoger en el negocio."
- `notify_admin_no_courier(order_id)`
  - Push y correo a superusuarios: "Pedido sin repartidor por más de 15 min."
- `notify_customer_no_courier_decision(order_id)`
  - "Pasaron 30 minutos. Elige recoger o cancelar."
- `notify_business_near_closing(order_id, minutes)`
  - "El negocio cierra en X minutos. ¿Aceptas el pedido?"
- `notify_customer_near_closing_cancelled(order_id)`
  - "El negocio no aceptó el pedido. Si pagaste por transferencia, el reembolso
    se procesa el siguiente día hábil."

Reutilizar `send_to_user`, `send_email` y el patrón de
`notify_admin_transfer_review`.

## 6. Frontend

### 6.1 Carrito del cliente

Archivo: `backend/templates/web/cart.html`

Nueva tarjeta `noCourierCard`:

- Aviso: "No hay repartidores disponibles ahora."
- Opción **Esperar 30 minutos**.
- Opción **Recoger en el negocio**.
- Si elige esperar, se envía `no_courier_action = "wait"`.
- Si elige recoger, se cambia `fulfillment_type` a `pickup` y se recalcula.

La tarjeta solo aparece si `res.no_courier` y el pedido es a domicilio.

### 6.2 Pedido del cliente

Archivo: `backend/templates/web/order_detail.html`

Banners:

- Pedido retenido: "Estamos buscando repartidor. Si no aparece en X minutos,
  podrás recoger o cancelar."
- A los 30 minutos: botones **Recoger en el negocio** y **Cancelar**.
- Pedido cerca del cierre: "El negocio está por cerrar; esperando confirmación."
- Cancelado por cierre: mensaje de reembolso.

### 6.3 Panel del negocio

Archivo: `backend/templates/web/restaurant_orders.html`

- Pedidos `near_closing` arriba y con borde amarillo.
- Badge "Cerca del cierre".
- Botones **Aceptar pedido** y **Rechazar**.
- Si es `no_courier_hold`, leyenda "Sin repartidor; no preparar todavía."
- Pedidos programados arriba, con borde morado y fecha/hora (Fase 2).
- Si intenta marcar listo un programado mucho antes, modal de advertencia
  (Fase 2).

### 6.4 Panel del administrador

Archivo: `backend/templates/web/dashboard_admin.html`

- Tarjeta "Pedidos sin repartidor".
- Modal de asignación de repartidor.
- Acciones descritas en 5.7.
- Confirmaciones claras para "Tomar" y "Cancelar".

## 7. Reglas de estados

| Situación | Estado | `requires_courier_approval` | `no_courier_hold` | Visible al negocio |
|---|---|---|---|---|
| Pedido normal | pending | false | false | Sí |
| Lejos, esperando repartidor | awaiting_courier | true | false | No |
| Sin repartidores, cliente espera | awaiting_courier | true | true | No |
| Cerca del cierre, sin repartidor | awaiting_courier | true | true | Sí, para aceptar |
| Cerca del cierre, con repartidor | pending | false | false | Sí |
| Admin toma el pedido | preparing/ready | false | false | Sí |
| Admin recoge | picked_up | false | false | Sí |
| Admin entrega | delivered | false | false | Sí |

## 8. Casos borde

1. **Sin repartidores y cerca del cierre**
   - El negocio ve el pedido para aceptar, pero no puede prepararlo hasta que
     haya repartidor.
   - Si no acepta en 10 minutos, se cancela.

2. **Cliente elige esperar y luego quiere recoger**
   - Puede cambiar a recoger desde el pedido antes de que el negocio empiece a
     preparar.
   - Si ya está pagado por transferencia, se reembolsa el envío al siguiente
     día hábil.

3. **El admin toma el pedido y luego aparece un repartidor**
   - El pedido ya no se ofrece a repartidores (`admin_delivery = true`).
   - El admin puede liberarlo manualmente si hace falta (Fase 2).

4. **Repartidor disponible pero saturado**
   - La disponibilidad cuenta solo a quienes pueden aceptar según su límite.
   - Si todos están saturados, se considera "sin repartidores".

5. **Repartidor marcado disponible pero inactivo**
   - Se usa `is_available` como señal principal.
   - Fase 3 puede usar última ubicación/actividad para afinar.

6. **Pedido de negocio con reparto propio**
   - No se aplica ninguna regla de TuPedidoJR.
   - Solo el apoyo voluntario de la Fase 2.

## 9. Pruebas

### Backend

Nuevos archivos:

- `backend/tests/test_delivery_ops.py`
- `backend/tests/test_admin_orders.py`
- `backend/tests/test_near_closing.py`
- Ampliar `backend/tests/test_schedule_service.py` si existe.

Casos mínimos:

1. `available_courier_count` cuenta solo disponibles y con cupo.
2. `estimate-price` devuelve `no_courier` cuando no hay repartidores.
3. Crear pedido a domicilio sin repartidores y sin elección → 409.
4. Crear con `no_courier_action = "wait"` → retenido y oculto al negocio.
5. Crear con `no_courier_action = "pickup"` → pickup sin retención.
6. Repartidor acepta → pedido visible al negocio y en preparación.
7. A los 15 minutos listo → se marca `courier_alert_at` y se notifica al admin.
8. A los 30 minutos → se avisa al cliente y se fija deadline de decisión.
9. Cliente no decide → se cancela y se reembolsa según política.
10. Admin asigna repartidor → se asigna y notifica.
11. Admin toma pedido → `admin_delivery` y no aparece a repartidores.
12. Admin marca recogido/entregado → estados correctos y sin pago a repartidor.
13. Cambio a recoger sin pago → ajusta envío y total.
14. Cambio a recoger con transferencia → reembolso pendiente.
15. Pedido cerca del cierre → deadline de 10 minutos.
16. Negocio acepta → se limpia `near_closing`.
17. Negocio no responde → se cancela y se avisa al cliente.
18. Pedido con reparto propio no se ve afectado.

### Frontend

Pruebas manuales en navegador:

1. Carrito sin repartidores muestra la tarjeta y permite esperar/recoger.
2. Pedido retenido no aparece en el panel del negocio.
3. Al aceptar un repartidor, aparece en el negocio.
4. Admin ve la alerta a los 15 minutos y puede asignar/tomar.
5. Admin marca recogido y entregado.
6. Pedido cerca del cierre se muestra con badge y botones.
7. Cliente ve el aviso de reembolso al siguiente día hábil.

## 10. Despliegue

1. Aplicar migración 078.
2. Desplegar con `DELIVERY_OPS_V2_ENABLED = false`.
3. Probar en local y en un negocio de prueba.
4. Activar la bandera en producción.
5. Monitorear:
   - Pedidos sin repartidor.
   - Alertas al admin.
   - Cancelaciones por cierre.
   - Reembolsos pendientes.

## 11. Fuera de alcance de la Fase 1

- Turnos de repartidores.
- Pronóstico de demanda.
- Apoyo de reparto para negocios con reparto propio (Fase 2).
- Recordatorio push/email de programados (Fase 2; el panel ya tiene aviso
  visual local).
- Reembolso automático por pasarela; se mantiene el registro pendiente y el
  administrador lo procesa.

## 12. Riesgos y decisiones abiertas

1. **Cambio a recoger con transferencia ya pagada**: se propone reembolso
   manual del envío al siguiente día hábil. Confirmar si se acepta.
2. **Perecederos**: se usará `business_type = "restaurant"` como perecedero y
   `store` como no perecedero. Si se necesita por producto, se agrega una marca
   en `menu_items`.
3. **Admin entrega**: no genera pago a repartidor; el envío queda como ingreso
   de la plataforma. Confirmar si se registra aparte para reportes.
4. **Disponibilidad real**: `is_available` puede estar desactualizado. Fase 3
   puede usar última actividad/ubicación.
5. **Notificaciones**: si el cliente no tiene push, el aviso queda en la
   pantalla del pedido y en correo si tiene correo configurado.

## 13. Implementación realizada en local

- Migración `078_delivery_ops.py`.
- Campos nuevos en `orders` y esquemas.
- `courier_availability.py` y `delivery_ops_service.py`.
- `admin_orders.py` con asignar, tomar, estado y cambio a recoger.
- Cambios en `orders.py`, `restaurants.py`, `delivery.py`, `schedule_service.py`,
  `push_service.py`, `tracking_service.py` y `courier_timeout_service.py`.
- Pantallas: carrito, detalle del pedido, pedidos del negocio y dashboard del
  administrador.
- Pruebas nuevas en `test_delivery_ops.py`.
- Suite completa: **438 pruebas aprobadas**.
- La bandera `DELIVERY_OPS_V2_ENABLED` quedó activada en local para pruebas.
  En producción debe desplegarse apagada y activarse después de validar.

## 14. Implementación de Fase 2

- Migración `079_scheduled_and_support.py`.
- Campos nuevos en `orders`:
  - `scheduled_outside_hours`
  - `scheduled_approval_status`
  - `scheduled_approval_deadline`
  - `scheduled_approved_at`
  - `scheduled_prep_ack`
  - `scheduled_prep_ack_at`
  - `scheduled_reminder_sent_at`
  - `courier_support_requested`
  - `courier_support_fee`
  - `courier_support_requested_at`
  - `courier_support_alert_at`
- `scheduled_service.py` valida preparación anticipada y aprobación fuera de
  horario.
- `delivery_ops_service.py` envía recordatorios de 1 hora, cancela programados
  fuera de horario sin respuesta y avisa al negocio cuando un apoyo de reparto
  sigue sin asignar.
- Endpoints nuevos:
  - `POST /restaurants/{id}/orders/{id}/scheduled-approval`
  - `POST /restaurants/{id}/orders/{id}/request-courier-support`
- El cargo de apoyo de reparto se suma a `restaurant_owes_platform` cuando el
  pedido se entrega, no antes.
- La UI del negocio muestra:
  - Pedidos programados arriba y con color.
  - Botones para aceptar o rechazar programados fuera de horario.
  - Aviso y botones para preparación anticipada de perecederos.
  - Botón de apoyo de TuPedidoJR para pedidos con reparto propio.
- La UI del cliente muestra el estado del programado fuera de horario y la
  preparación anticipada.
- Recordatorio push al negocio 1 hora antes del pedido programado.

## 15. Otros ajustes de interfaz

- Se quitó “Descargar app” del menú principal para acortar la navegación.
  El enlace se mantiene en el login y en la landing.
- Cuando una sesión expira, cualquier llamada autenticada que reciba 401
  limpia la sesión y redirige a `/web/login?next=...` en lugar de mostrar el
  mensaje de token inválido.


## 14. Cómo probar en local

1. En `Configuración → Envíos`, confirma que
   `DELIVERY_OPS_V2_ENABLED` esté activado.
2. Marca al repartidor como no disponible desde su panel o desde
   `Admin → Repartidores`.
3. Haz un pedido a domicilio en un negocio con reparto de TuPedidoJR.
4. En el carrito debe aparecer el aviso de sin repartidores y las opciones
   esperar o recoger.
5. En `Admin → Operación en vivo` aparece la tarjeta
   `Pedidos sin repartidor`.
6. Usa `Tomar`, `Recogí` y `Entregué` para probar el reparto del admin.
7. Para probar los tiempos sin esperar, cambia en la base de datos
   `courier_approval_deadline`, `no_courier_decision_deadline` o
   `business_confirmation_deadline`, o baja los minutos en Configuración.
8. Para probar cerca del cierre, publica un horario que cierre pronto y sube
   `NEAR_CLOSING_MIN`, o crea el pedido unos minutos antes del cierre.
9. Al terminar, vuelve a marcar al repartidor como disponible.


