"""Crea o actualiza el primer administrador sin borrar datos.

Uso:
    ADMIN_EMAIL=admin@dominio.com \\
    ADMIN_PASSWORD='una-clave-larga' \\
    ADMIN_NAME='Administrador' \\
    python scripts/create_admin.py
"""

import asyncio
import os
import sys
import uuid
from pathlib import Path

# Permite ejecutar `python scripts/create_admin.py` desde /app.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import async_session
from app.models.user import User


async def main() -> None:
    email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    password = os.getenv("ADMIN_PASSWORD") or ""
    name = (os.getenv("ADMIN_NAME") or "Administrador").strip()

    if not email or "@" not in email:
        print("Falta ADMIN_EMAIL válido.", file=sys.stderr)
        raise SystemExit(1)
    if len(password) < 8:
        print("ADMIN_PASSWORD debe tener al menos 8 caracteres.", file=sys.stderr)
        raise SystemExit(1)

    async with async_session() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user:
            user.name = name
            user.password_hash = hash_password(password)
            user.is_active = True
            user.is_superuser = True
            print(f"Administrador actualizado: {email}")
        else:
            user = User(
                id=uuid.uuid4(),
                name=name,
                email=email,
                password_hash=hash_password(password),
                is_active=True,
                is_superuser=True,
            )
            db.add(user)
            print(f"Administrador creado: {email}")
        await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
