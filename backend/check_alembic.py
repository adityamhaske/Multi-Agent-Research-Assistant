import asyncio
from app.config import settings
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
async def main():
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT * FROM alembic_version"))
        print(res.fetchall())
    await engine.dispose()
asyncio.run(main())
