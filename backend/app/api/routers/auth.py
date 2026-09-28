import os
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.async_session import get_async_db
from app.auth.password import verify_password
from app.auth.jwt import create_access_token, verify_token
from app.crud import user as crud_user
from app.crud import tenant as crud_tenant

router = APIRouter(prefix="/auth", tags=["auth"])

# Read from env so 'secure' is False locally and True in production (HTTPS)
IS_PRODUCTION = os.getenv("ENV", "development") == "production"

COOKIE_NAME = "access_token"
COOKIE_MAX_AGE = 60 * 60 * 24  # 1 day in seconds — matches JWT expiry


# ── Schemas ──────────────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    organization_name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    message: str
    user_id: str
    tenant_id: str


# ── Helper ───────────────────────────────────────────────────────────────────

def _set_auth_cookie(response: Response, token: str) -> None:
    """
    Sets the JWT as an HttpOnly cookie on the response.
    - httponly=True   → JavaScript cannot read this cookie (XSS protection)
    - secure=True     → only sent over HTTPS (set False locally)
    - samesite='lax'  → cookie sent on same-site requests + top-level GET navigations
                        blocks CSRF form-POST attacks from other domains
    """
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="lax",
        max_age=COOKIE_MAX_AGE,
    )


# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("/signup", response_model=AuthResponse)
async def signup(
    request: SignupRequest,
    response: Response,                          # FastAPI injects the response object
    db: AsyncSession = Depends(get_async_db),
):
    # 1. Check email uniqueness
    if await crud_user.get_user_by_email(db, request.email):
        raise HTTPException(status_code=400, detail="Email already registered")

    # 2. Check org name uniqueness
    if await crud_tenant.get_tenant_by_name(db, request.organization_name):
        raise HTTPException(status_code=400, detail="Organization name already taken")

    # 3. Create tenant + user atomically
    user, tenant = await crud_user.create_tenant_and_user(
        db,
        request.email,
        request.password,
        request.organization_name,
    )

    # 4. Create JWT
    token = create_access_token(data={"sub": str(user.id), "tenant_id": str(tenant.id)})

    # 5. Set it as an HttpOnly cookie — NOT returned in the body
    _set_auth_cookie(response, token)

    return AuthResponse(
        message="Account created",
        user_id=str(user.id),
        tenant_id=str(tenant.id),
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    request: LoginRequest,
    response: Response,                          # FastAPI injects the response object
    db: AsyncSession = Depends(get_async_db),
):
    # 1. Fetch user
    user = await crud_user.get_user_by_email(db, request.email)

    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    # 2. Create JWT
    token = create_access_token(data={"sub": str(user.id), "tenant_id": str(user.tenant_id)})

    # 3. Set HttpOnly cookie — token never touches the response body
    _set_auth_cookie(response, token)

    return AuthResponse(
        message="Login successful",
        user_id=str(user.id),
        tenant_id=str(user.tenant_id),
    )


@router.post("/logout")
async def logout(response: Response):
    """
    Clears the auth cookie. The JWT itself is still technically valid until
    expiry (JWTs are stateless), but the browser no longer sends it.
    For a true blacklist you'd need a Redis revocation store — out of scope for now.
    """
    response.delete_cookie(
        key=COOKIE_NAME,
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="lax",
    )
    return {"message": "Logged out"}


@router.get("/me")
async def me(request: Request):
    """
    Convenience endpoint — returns who the caller is, purely from the cookie.
    Useful for the frontend to check login state on page load without
    calling a protected route.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = verify_token(token)
    return {
        "user_id": payload.get("sub"),
        "tenant_id": payload.get("tenant_id"),
    }
