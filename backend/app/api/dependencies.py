from fastapi import HTTPException, Request, status
from app.auth.jwt import verify_token


def get_current_tenant_id(request: Request) -> str:
    """
    Reads the JWT from the HttpOnly cookie (not the Authorization header).
    Every route that uses Depends(get_current_tenant_id) automatically
    gets this new cookie-based auth — no changes needed in those routes.
    """
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated — no access_token cookie found",
        )
    payload = verify_token(token)  # raises HTTP 403 if invalid or expired
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant_id in token")
    return tenant_id


def get_current_user_id(request: Request) -> str:
    """
    Same cookie read — extracts the user's sub (user ID) from the JWT.
    """
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated — no access_token cookie found",
        )
    payload = verify_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=403, detail="No user_id in token")
    return user_id
