#!/bin/sh
set -e

echo "Aplicando migraciones de base de datos..."
attempt=0
until alembic upgrade head; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 20 ]; then
    echo "No se pudieron aplicar las migraciones después de $attempt intentos."
    exit 1
  fi
  echo "Base de datos no disponible todavía. Reintentando en 3 s..."
  sleep 3
done

# Un solo worker: el manejo de WebSockets y el estado en memoria viven en el proceso.
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --proxy-headers \
  --forwarded-allow-ips="*" \
  --workers 1
