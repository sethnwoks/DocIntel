from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.models import User, Tenant
from app.auth.password import hash_password

async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()

async def create_tenant_and_user(db: AsyncSession, email: str, password: str, org_name: str) -> tuple[User, Tenant]:
    # Create the tenant using ORM
    tenant = Tenant(name=org_name)
    db.add(tenant)
    await db.flush()  # We flush so SQLAlchemy fetches the new tenant.id from Postgres
    
    # Create the user using ORM
    hashed_pw = hash_password(password)
    user = User(
        email=email,
        hashed_password=hashed_pw,
        tenant_id=tenant.id,
        is_active=True
    )
    db.add(user)
    await db.commit()  # Commits both tenant and user atomically
    await db.refresh(user)
    
    return user, tenant
