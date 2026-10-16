import re
from datetime import timedelta
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pwdlib import PasswordHash
from pydantic import BaseModel, field_validator
from sqlmodel import select

from web.db import User, session, utcnow

COOKIE = "pdd_session"
MIN_PASSWORD = 8
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
hasher = PasswordHash.recommended()  # Argon2
# Verifying against this when the email is unknown takes as long as a real check, so response times
# don't reveal which emails have accounts.
_DUMMY_HASH = hasher.hash("not-a-real-password")

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not EMAIL.match(value):
            raise ValueError("Enter a valid email address.")
        return value


class UserOut(BaseModel):
    id: int
    email: str


def _set_session(response: Response, request: Request, user: User) -> None:
    settings = request.app.state.settings
    expires = utcnow() + timedelta(days=settings.session_days)
    token = jwt.encode({"sub": str(user.id), "exp": expires}, settings.secret_key, algorithm="HS256")
    # httpOnly: page scripts can't read it; SameSite=Lax: other sites can't send it with their requests.
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=settings.cookie_secure,
                        max_age=settings.session_days * 86400, path="/")


def current_user(request: Request) -> User:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in.")
    try:
        user_id = int(jwt.decode(token, request.app.state.settings.secret_key, algorithms=["HS256"])["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired; log in again.")
    with session(request.app.state.engine) as db:
        user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found.")
    return user


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserOut)
def register(body: Credentials, request: Request, response: Response):
    settings = request.app.state.settings
    if not settings.allow_signup:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign-up is closed; ask an administrator for an account.")
    domain = body.email.rsplit("@", 1)[1]
    if settings.signup_domains and domain not in settings.signup_domains:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"Sign-up is limited to {', '.join('@' + d for d in settings.signup_domains)} addresses.")
    if len(body.password) < MIN_PASSWORD:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"The password needs at least {MIN_PASSWORD} characters.")
    with session(request.app.state.engine) as db:
        if db.exec(select(User).where(User.email == body.email)).first():
            raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")
        user = User(email=body.email, password_hash=hasher.hash(body.password))
        db.add(user)
        db.commit()
        db.refresh(user)
    _set_session(response, request, user)
    return UserOut(id=user.id, email=user.email)


@router.post("/login", response_model=UserOut)
def login(body: Credentials, request: Request, response: Response):
    with session(request.app.state.engine) as db:
        user = db.exec(select(User).where(User.email == body.email)).first()
    valid = hasher.verify(body.password, user.password_hash if user else _DUMMY_HASH)
    if not (user and valid):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password.")
    _set_session(response, request, user)
    return UserOut(id=user.id, email=user.email)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return UserOut(id=user.id, email=user.email)
