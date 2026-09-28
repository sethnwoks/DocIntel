from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models import Tenant

async def get_tenant_by_name(db: AsyncSession, name: str) -> Tenant | None:
    result = await db.execute(select(Tenant).where(Tenant.name == name))
    return result.scalar_one_or_none()
