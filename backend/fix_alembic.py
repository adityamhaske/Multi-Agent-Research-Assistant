import asyncio
from app.config import settings
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
async def main():
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        await conn.execute(text("UPDATE alembic_version SET version_num = '0008_chat_threads'"))
        await conn.commit()
    await engine.dispose()
asyncio.run(main())
