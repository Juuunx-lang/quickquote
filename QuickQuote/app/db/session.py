from collections.abc import AsyncGenerator
from urllib.parse import quote_plus

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings


def _build_mysql_url(host: str, port: int, user: str, password: str, database: str) -> str:
    return (
        f"mysql+aiomysql://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{quote_plus(database)}?charset=utf8mb4"
    )


DATABASE_URL = _build_mysql_url(
    host=settings.PURCHASE_DB_HOST or settings.MYSQL_HOST,
    port=settings.PURCHASE_DB_PORT or settings.MYSQL_PORT,
    user=settings.PURCHASE_DB_USER or settings.MYSQL_USER,
    password=settings.PURCHASE_DB_PASSWORD or settings.MYSQL_PASSWORD,
    database=settings.PURCHASE_DB_NAME or settings.MYSQL_DB,
)
GOODS_DATABASE_URL = _build_mysql_url(
    host=settings.ORDER_DB_HOST or settings.GOODS_MYSQL_HOST,
    port=settings.ORDER_DB_PORT or settings.GOODS_MYSQL_PORT,
    user=settings.ORDER_DB_USER or settings.GOODS_MYSQL_USER,
    password=settings.ORDER_DB_PASSWORD or settings.GOODS_MYSQL_PASSWORD,
    database=settings.ORDER_DB_NAME or settings.GOODS_MYSQL_DB,
)

engine = create_async_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_timeout=30,
    pool_size=10,
    max_overflow=20,
)
goods_engine = create_async_engine(
    GOODS_DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_timeout=30,
    pool_size=10,
    max_overflow=20,
)
AsyncSessionLocal = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
AsyncSessionGoodsLocal = async_sessionmaker(bind=goods_engine, autoflush=False, expire_on_commit=False)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_goods_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionGoodsLocal() as session:
        yield session
