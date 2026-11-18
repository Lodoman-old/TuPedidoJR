# API de recargas (tiempo aire y pago de servicios)

Estado actual: **no implementada**. Solo existe la página informativa `/web/recargas`
con el aviso “Próximamente”. Este documento define cómo se usaría una vez
integrado el proveedor.

## 1. Alcance

- **Tiempo aire**: Telcel, AT&T, Movistar, Bait, Unefon y los que agregue el proveedor.
- **Pago de servicios**: CFE, agua, Telmex, predial (según catálogo del proveedor).
- Pagos con **Mercado Pago** o **transferencia**. No se recomienda efectivo por el
  riesgo de fraude; si se habilita, solo para clientes con historial.

## 2. Modelo de datos (nuevo)

### `recharge_orders`
| Campo | Tipo | Nota |
|---|---|---|
| id | UUID | PK |
| user_id | UUID | quien paga |
| kind | varchar(20) | `airtime` o `service` |
| company | varchar(40) | Telcel, CFE, etc. |
| reference | varchar(60) | teléfono a 10 dígitos o número de servicio |
| amount | numeric(10,2) | monto que recibe el destino |
| commission | numeric(10,2) | ganancia de la plataforma |
| total | numeric(10,2) | lo que paga el cliente |
| status | varchar(20) | ver estados |
| payment_method | varchar(20) | `mp`, `transfer` |
| payment_id | varchar(120) | id en Mercado Pago |
| provider | varchar(40) | proveedor usado |
| provider_order_id | varchar(120) | referencia enviada al proveedor |
| provider_reference | varchar(120) | folio devuelto por el proveedor |
| failure_code | varchar(40) | motivo si falla |
| idempotency_key | varchar(80) | único por usuario |
| created_at / paid_at / completed_at / refunded_at | timestamptz | |

### `recharge_events`
Bitácora de cada cambio de estado (quién, cuándo, respuesta del proveedor).

## 3. Endpoints

Base: `/api/v1/recharges` (requiere sesión, salvo catálogo).

### `GET /recharges/catalog`
Público. Devuelve compañías, montos permitidos y comisión vigente.
```json
{
  "enabled": true,
  "min": 20, "max": 500,
  "companies": [
    {"code": "telcel", "name": "Telcel", "amounts": [20, 50, 100, 200, 300]},
    {"code": "cfe", "name": "CFE", "kind": "service"}
  ],
  "commission_percent": 5.0
}
```

### `POST /recharges/quote`
Valida y cotiza sin cobrar.
```json
{"kind": "airtime", "company": "telcel", "reference": "4121234567", "amount": 100}
```
Respuesta:
```json
{"amount": 100, "commission": 5, "total": 105, "available": true}
```

### `POST /recharges`
Crea la orden y el intento de pago. Requiere `Idempotency-Key` (UUID) para no
duplicar si el cliente reintenta.
```json
{"kind": "airtime", "company": "telcel", "reference": "4121234567", "amount": 100, "payment_method": "mp"}
```
Respuesta `201`:
```json
{"id": "...", "status": "awaiting_payment", "total": 105, "payment_url": "https://..."}
```

### `GET /recharges/{id}`
Estado, folio y comprobante. Solo el dueño (o admin).

### `GET /recharges`
Historial paginado del cliente.

### `POST /recharges/{id}/cancel`
Solo si sigue en `awaiting_payment` o `created`.

### `POST /recharges/{id}/retry`
Solo si quedó `failed` y **no** se reembolsó. Reenvía al proveedor con la misma
referencia para no duplicar.

### Webhooks
- `POST /api/v1/payments/webhook/mercadopago`: verifica firma; si el pago se
  aprueba, marca la orden como `paid` y dispara la recarga.
- `POST /api/v1/recharges/webhook/{provider}`: el proveedor confirma
  `completed`/`failed`. Se valida un secreto compartido.

### Administración
- `GET /api/v1/admin/recharges`: filtros por estado, fecha, compañía; totales y comisión.
- `POST /api/v1/admin/recharges/{id}/refund`: reembolso manual.
- `GET /api/v1/admin/recharges/provider-status`: saldo y conectividad del proveedor.

## 4. Estados

```
created -> awaiting_payment -> paid -> sending -> completed
                    |                        |
                    v                        v
                 expired                    failed -> refunded
```

- `completed` **solo** con folio del proveedor.
- Si el proveedor no responde, la orden se queda en `sending` y un proceso de
  conciliación consulta el estado cada 5 minutos antes de reintentar o reembolsar.

## 5. Reglas de negocio

- Montos permitidos: 20, 50, 100, 150, 200, 300, 500 (configurable).
- Comisión: porcentaje o monto fijo, visible antes de pagar.
- **Nunca** se envía dos veces la misma recarga: se usa `provider_order_id` y el
  proveedor debe ser idempotente.
- Límite diario por usuario (ej. 3 recargas o $1,000) para frenar fraude.
- Validación del teléfono: 10 dígitos, compañía coherente con el prefijo.
- Comprobante por correo y en la app; opcional por WhatsApp.
- Cualquier intento repetido o monto raro se registra en `security_events`.

## 6. Seguridad

- Sesión obligatoria + `Idempotency-Key`.
- Webhooks con firma; si la firma no coincide, se ignora y se registra el intento.
- Nunca se confía en el navegador para el monto: se recalcula en el servidor.
- Límite de solicitudes por IP (ya existe) y por cuenta.
- Los datos del proveedor (llave/API key) viven en ajustes, nunca en el frontend.

## 7. Ajustes nuevos (panel admin, grupo “Recargas”)

`RECHARGE_ENABLED`, `RECHARGE_COMMISSION_PERCENT`, `RECHARGE_MIN`,
`RECHARGE_MAX`, `RECHARGE_DAILY_LIMIT`, `RECHARGE_PROVIDER`,
`RECHARGE_PROVIDER_KEY`, `RECHARGE_PROVIDER_URL`, `RECHARGE_WEBHOOK_SECRET`.

## 8. Flujo (resumen)

1. El cliente elige compañía, número y monto.
2. Se cotiza (monto + comisión).
3. Se crea la orden y el pago.
4. Mercado Pago confirma por webhook.
5. Se envía la recarga al proveedor con una referencia única.
6. El proveedor responde con folio → `completed`.
7. Si falla o no se aplicó → reembolso automático.
