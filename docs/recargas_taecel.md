# Recargas con Taecel (descripción simple)

## Qué es

TuPedidoJR vende **tiempo aire** (Telcel, AT&T, Movistar, Bait, Unefon…) usando
**Taecel** como proveedor. La plataforma tiene una **bolsa de saldo en Taecel** y
desde ahí se envían las recargas.

Hay dos formas de comprarla:

1. **En línea**: el cliente paga con Mercado Pago o transferencia desde la app.
2. **En efectivo con el repartidor**: el repartidor la vende en la calle, cobra
   en efectivo y después entrega ese dinero a la plataforma.

## Flujo en línea (4 pasos)

1. El cliente elige compañía, número y monto.
2. Paga con Mercado Pago o transferencia.
3. TuPedidoJR manda la recarga a Taecel.
4. Taecel confirma y se muestra el **folio** como comprobante.

Si Taecel rechaza, se reembolsa automáticamente.

## Flujo en efectivo con el repartidor

La idea: **el repartidor cobra primero y luego recarga**.

1. El cliente le pide una recarga al repartidor.
2. El repartidor la captura en su app: compañía, número y monto.
3. La app le muestra: “Cobra **$105** en efectivo. Deberás **$100** a la plataforma”.
4. El repartidor **cobra el efectivo** al cliente.
5. Confirma en la app y TuPedidoJR envía la recarga a Taecel.
6. Taecel confirma: se muestra el **folio** al cliente.
7. El repartidor queda debiendo **$100**. Ese monto se **descuenta en su corte**.

El **servicio ($5)** se lo queda el repartidor. La plataforma recupera el monto
de la recarga porque ya lo pagó a Taecel.

### Reglas del efectivo

- **Primero cobra, después recarga.** Si recarga sin cobrar, él asume el riesgo.
- Si Taecel falla, **no hay deuda**: no se cobra o se devuelve el efectivo.
- Tiene un **límite diario** de recargas en efectivo (ej. $500) y un tope de
  deuda pendiente. Al llegar al tope, la app no lo deja enviar más hasta su corte.
- La deuda aparece en **Ganancias / Corte** como “Recargas en efectivo” y se
  resta del saldo del repartidor.
- Solo repartidores activos pueden vender recargas.

### Saldo de Taecel

- El panel de administración muestra la **bolsa disponible**.
- Si el saldo baja de un mínimo, se avisa al administrador.
- Cada recarga descuenta de la bolsa; por eso el control de deuda del repartidor
  es lo que protege el dinero de la plataforma.

## Resumen en una frase

> El cliente paga en la app o en efectivo al repartidor; TuPedidoJR recarga desde
> su saldo de Taecel y entrega el folio. En efectivo, el repartidor se queda el
> servicio y devuelve el monto de la recarga en su corte.
