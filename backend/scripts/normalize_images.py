"""Normalize every local upload to a square 800x800 WebP.

Run once after deploying the image pipeline change:

    python -m scripts.normalize_images
"""
import asyncio
import uuid
from pathlib import Path

from sqlalchemy import select

from app.db.session import async_session
from app.models.menu_item import MenuItem
from app.models.restaurant import Restaurant
from app.services.file_service import UPLOAD_DIR, delete_upload

SIZE = 800


def _normalize(path: Path) -> Path:
    from app.services.file_service import _compress

    content = path.read_bytes()
    processed = _compress(content, SIZE, 82)
    destination = UPLOAD_DIR / f"{uuid.uuid4().hex}.webp"
    destination.write_bytes(processed)
    return destination


async def main():
    normalized = 0
    async with async_session() as db:
        restaurants = (
            await db.execute(select(Restaurant).where(Restaurant.logo_url.isnot(None)))
        ).scalars().all()
        for restaurant in restaurants:
            old = restaurant.logo_url
            if not old or not old.startswith("/static/uploads/"):
                continue
            path = UPLOAD_DIR / Path(old).name
            if not path.exists():
                continue
            new_path = _normalize(path)
            restaurant.logo_url = f"/static/uploads/{new_path.name}"
            delete_upload(old)
            normalized += 1

        items = (
            await db.execute(select(MenuItem).where(MenuItem.image_url.isnot(None)))
        ).scalars().all()
        for item in items:
            old = item.image_url
            if not old or not old.startswith("/static/uploads/"):
                continue
            path = UPLOAD_DIR / Path(old).name
            if not path.exists():
                continue
            new_path = _normalize(path)
            item.image_url = f"/static/uploads/{new_path.name}"
            delete_upload(old)
            normalized += 1

        await db.commit()

    print(f"Imágenes normalizadas: {normalized}")


if __name__ == "__main__":
    asyncio.run(main())
