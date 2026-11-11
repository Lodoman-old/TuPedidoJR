from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.setting import Setting


async def get_setting(db: AsyncSession, key: str, default: Any = None) -> str | None:
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        return setting.value
    return default


async def set_setting(db: AsyncSession, key: str, value: str, description: str = "") -> Setting:
    result = await db.execute(select(Setting).where(Setting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
        if description:
            setting.description = description
    else:
        setting = Setting(key=key, value=value, description=description)
        db.add(setting)
    await db.commit()
    await db.refresh(setting)
    return setting
