import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Use asyncpg driver
ASYNC_DATABASE_URL = os.getenv(
    "ASYNC_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@postgres:5432/rag_db"
)

# Engine with connection pool
async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=False,              # set True to log SQL queries during development
    pool_size=20,
    max_overflow=40,
    pool_pre_ping=True,
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# Dependency for FastAPI endpoints
async def get_async_db():
    async with AsyncSessionLocal() as session:
        yield session
