# Pruebas en dispositivos reales

Guía para validar TuPedidoJR en Android (gama baja) e iOS (PWA) antes de
publicar. Marca cada casilla en cada dispositivo.

## Preparación

- [ ] Backend publicado con **HTTPS** y dominio real.
- [ ] `PUSH_ENABLED=true` con credenciales de Firebase cargadas.
- [ ] `DEBUG=false`, `SECRET_KEY` propia y contraseña de base de datos cambiada.
- [ ] APK instalado con la última versión (`versionCode` correcto).
- [ ] Usuarios de prueba: cliente, dueño de restaurante y repartidor.

## Android — gama baja (2 GB RAM o menos)

### Instalación
- [ ] Descargar el APK desde `/web/app` en el navegador del teléfono.
- [ ] Permitir "Instalar apps desconocidas" para el navegador.
- [ ] La instalación termina sin errores.
- [ ] El ícono y el nombre **TuPedidoJR** se muestran correctamente.

### Primer arranque
- [ ] Abre en menos de 15 segundos.
- [ ] No se cierra ni muestra pantalla en blanco.
- [ ] El inicio de sesión funciona con datos móviles y con Wi-Fi.

### Cliente
- [ ] Lista de restaurantes carga y muestra abierto/cerrado.
- [ ] Abrir un restaurante muestra el menú y el horario.
- [ ] Agregar al carrito y cambiar cantidades funciona.
- [ ] C.P. + colonia + calle resuelven la ubicación.
- [ ] El mapa carga los tiles (ArcGIS).
- [ ] Crear pedido en efectivo funciona.
- [ ] El pedido aparece en "Mis pedidos".
- [ ] El seguimiento muestra timeline y mapa.
- [ ] Cancelar un pedido pendiente pide motivo y funciona.
- [ ] Intentar cancelar un pedido en preparación muestra el mensaje de política.

### Repartidor
- [ ] Al entrar pide permiso de ubicación.
- [ ] La lista muestra restaurante, distancia y tiempo estimado.
- [ ] La lista se ordena del más cercano al más lejano.
- [ ] Aceptar, recoger y entregar funcionan.
- [ ] La ubicación se sigue enviando con la app abierta.
- [ ] Con la app cerrada se detiene el reporte (limitación conocida).

### Notificaciones
- [ ] Al crear un pedido llega notificación al restaurante.
- [ ] Al cambiar de estado llega notificación al cliente.
- [ ] Al asignar repartidor llega notificación al repartidor.
- [ ] Tocar la notificación abre la pantalla correcta.

### Rendimiento
- [ ] Desplazarse por el menú no se siente trabado.
- [ ] El consumo de batería en 30 minutos de uso es razonable.
- [ ] La app no se cierra al rotar o cambiar de red.

## iOS — PWA (Safari)

- [ ] Abrir el sitio con **HTTPS** en Safari.
- [ ] Compartir → **Agregar a pantalla de inicio**.
- [ ] El ícono aparece y abre en modo standalone.
- [ ] Iniciar sesión funciona.
- [ ] El GPS pide permiso y muestra la ubicación.
- [ ] Crear un pedido funciona.
- [ ] El seguimiento muestra mapa y timeline.
- [ ] Las notificaciones solo funcionan desde la PWA instalada (no en Safari normal).
- [ ] Al pedir permiso de notificaciones, se recibe el token sin errores.
- [ ] La app no pierde la sesión al cerrarla y volver a abrir.

## Administración (escritorio y móvil)

- [ ] `/web/admin/settings` solo es visible para el superusuario.
- [ ] Cambiar la comisión y guardar se refleja en un pedido nuevo.
- [ ] `/web/admin/reports` muestra totales y tablas del periodo.
- [ ] La descarga de `pedidos.csv` abre correctamente en Excel.
- [ ] La descarga de `liquidaciones.csv` abre correctamente en Excel.
- [ ] El restaurante puede editar su horario desde "Horario".
- [ ] Al cerrar el horario, un cliente no puede crear pedidos (error claro).
- [ ] El restaurante puede cancelar un pedido en preparación con motivo.
- [ ] El motivo y el reembolso se ven en el detalle del pedido.

## Redes y casos límite

- [ ] Sin conexión: la app muestra un error entendible (no se queda cargando).
- [ ] Conexión lenta (3G): las pantallas cargan con indicador.
- [ ] Cambio de Wi-Fi a datos móviles durante un pedido: el seguimiento se recupera.
- [ ] Zona horaria del teléfono distinta: los horarios del restaurante se calculan con `America/Mexico_City`.
- [ ] Pedido con nota y con cupón: se guardan y se muestran.

## Criterio de aceptación

Se considera listo para publicar cuando:

1. Todas las casillas de **Android** e **iOS** están marcadas.
2. No hay errores en la consola del navegador ni caídas de la app.
3. Los reportes cuadran con los pedidos del periodo.
4. Las notificaciones llegan en los tres roles.
