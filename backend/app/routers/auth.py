from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.auth import SESSION_COOKIE, DbSession, LoginLocked, authenticate, issue_session_token
from app.config import get_settings
from app.routers.meta import staff_out

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    employee_code: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=200)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: DbSession) -> dict:
    try:
        staff = authenticate(db, body.employee_code, body.password, request)
    except LoginLocked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many wrong attempts. Try again in 15 minutes.",
        ) from None
    if staff is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong employee code or password")

    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        issue_session_token(staff),
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/api",
    )
    return staff_out(staff)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    # No auth required: an expired session must still be able to clear its cookie.
    response.delete_cookie(SESSION_COOKIE, path="/api")
