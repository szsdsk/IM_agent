from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from typing import AsyncGenerator

from backend.config import settings


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_sqlite_schema_patches(conn)


async def _run_sqlite_schema_patches(conn) -> None:
    """为本地旧 SQLite 数据库补齐后续版本新增的列。"""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return

    documents_columns = {
        row[1]
        for row in (await conn.exec_driver_sql("PRAGMA table_info(documents)")).fetchall()
    }
    missing_document_columns = {
        "lark_doc_id": "VARCHAR(100)",
        "lark_doc_url": "VARCHAR(500)",
        "last_edited_by": "VARCHAR(100)",
        "last_edited_at": "DATETIME",
    }

    for column_name, column_type in missing_document_columns.items():
        if column_name not in documents_columns:
            await conn.execute(text(f"ALTER TABLE documents ADD COLUMN {column_name} {column_type}"))
