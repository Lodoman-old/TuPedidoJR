/* Local municipality tiles with automatic Esri fallback. */
(function () {
  const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}';

  window.createLocalTileLayer = function (options) {
    if (typeof L === 'undefined') return null;
    const opts = Object.assign({
      attribution: 'Tiles © Esri — Esri, HERE, Garmin, © OpenStreetMap contributors',
      maxZoom: 19,
      maxNativeZoom: 19,
    }, options || {});

    const local = L.tileLayer('/tiles/{z}/{y}/{x}.jpg', opts);
    local.on('tileerror', function (event) {
      const img = event && event.tile;
      const coords = event && event.coords;
      if (!img || !coords || img.dataset.esriFallback === '1') return;
      img.dataset.esriFallback = '1';
      img.src = ESRI
        .replace('{z}', coords.z)
        .replace('{y}', coords.y)
        .replace('{x}', coords.x);
    });
    return local;
  };
})();
