"""Verify DB schema and data after migration."""
import asyncio
from app.db.session import async_session
from sqlalchemy import text


async def verify():
    async with async_session() as db:
        result = await db.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name"
        ))
        tables = [r[0] for r in result]
        print("Tables:", tables)

        for tbl in ["restaurants", "delivery_persons", "orders", "delivery_payouts", "restaurant_payouts", "mandados", "cash_advances"]:
            if tbl in tables:
                result = await db.execute(text(
                    f"SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='{tbl}' ORDER BY ordinal_position"
                ))
                cols = [r[0] for r in result]
                print(f"  {tbl}: {cols}")
            else:
                print(f"  {tbl}: MISSING!")


if __name__ == "__main__":
    asyncio.run(verify())
