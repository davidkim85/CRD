from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.configurations.config import DATABASE_URL

engine = create_async_engine(DATABASE_URL,echo=True)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session
