# Recargas: flujo acordado

Documento de trabajo para implementar cuando se elija proveedor de recargas.

## Estado

- **Pendiente:** integración con proveedor.
- Telcel pide $5,000 MXN anticipados para habilitar la API; se están evaluando otras opciones.
- Compañías, montos y disponibilidad se tomarán de la API del proveedor.

## Reglas

- La comisión del repartidor es de **$2 MXN**, **aparte** del monto de la recarga.
- El saldo de las recargas se descuenta de la **bolsa prepago de la plataforma** con la compañía.
- El repartidor **no pone dinero de su bolsa**; solo cobra al cliente y entrega después.
- **Portal:** el cliente paga por transferencia. No hay comisión y no participa el repartidor.
- **Efectivo:** solo cuando el cliente pide la recarga al repartidor.

## Flujo durante una entrega

1. El repartidor abre **Confirmar entrega**.
2. Aparece una ventana opcional: **¿El cliente quiere una recarga?**
   - Compañía.
   - Número de teléfono.
   - Monto.
   - Comisión de $2.
   - Total a cobrar = monto + $2.
3. Si el cliente rechaza, se cierra la entrega normal.
4. Si acepta:
   - El cliente paga primero (monto + $2).
   - El repartidor marca **Pago recibido**.
   - Se ejecuta la recarga con el proveedor.
   - Se muestra confirmación y comprobante.
5. Registro:
   - **$2** de ganancia para el repartidor.
   - **Monto de la recarga** como deuda del repartidor con la plataforma.
   - Movimiento reflejado en su próximo corte.

La ventana aparece en cada entrega que cierre el repartidor, sin importar si el pedido se pagó en efectivo o por transferencia, y también en pedidos para recoger.

## Flujo sin pedido

El repartidor puede ofrecer recargas por su cuenta (familia, conocidos):

1. Entra a **Recargas** en su panel.
2. Elige compañía, número y monto.
3. Cobra **monto + $2**.
4. Confirma el pago.
5. Se ejecuta la recarga.
6. Queda como **recarga suelta**, con la misma contabilidad:
   - $2 de ganancia para el repartidor.
   - Monto como deuda con la plataforma.

## Reintentos y fallas

- Si el cliente no paga, no se ejecuta la recarga.
- Si la recarga falla después del pago, se puede **reintentar**.
- Si vuelve a fallar, se **devuelve el efectivo en ese momento**: monto + $2.
- La recarga queda como **fallida/reembolsada**.
- El repartidor no gana comisión ni queda con deuda.

## Contabilidad

- Deuda del repartidor: monto de la recarga.
- Ganancia del repartidor: $2.
- Saldo del proveedor: disminuye por el monto de la recarga.
- Portal con transferencia: sin comisión; solo se registra la recarga.

## Requisitos de integración

- Credenciales/API key.
- Ambiente de pruebas.
- Catálogo de compañías y montos.
- Endpoint para ejecutar la recarga.
- Consulta de estado y webhook de confirmación.
- Saldo prepago disponible.
