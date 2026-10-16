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


def normalize_email(value: str) -> str:
    value = value.strip().lower()
    if not EMAIL.match(value):
        raise ValueError("Enter a valid email address.")
    return value


class Credentials(BaseModel):
    email: str
    password: str

    _email = field_validator("email")(normalize_email)


class Registration(Credentials):
    name: str = ""


class UserOut(BaseModel):
    id: int
    email: str
    name: str

    @classmethod
    def of(cls, user: User) -> "UserOut":
        return cls(id=user.id, email=user.email, name=user.name or "")


class ProfileUpdate(BaseModel):
    name: str
    email: str

    _email = field_validator("email")(normalize_email)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


def _check_email_allowed(settings, email: str) -> None:
    domain = email.rsplit("@", 1)[1]
    if settings.signup_domains and domain not in settings.signup_domains:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"Accounts are limited to {', '.join('@' + d for d in settings.signup_domains)} addresses.")


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"The password needs at least {MIN_PASSWORD} characters.")


def _set_session(response: Response, request: Request, user: User) -> None:
    settings = request.app.state.settings
    expires = utcnow() + timedelta(days=settings.session_days)
    token = jwt.encode({"sub": str(user.id), "ver": user.session_version or 0, "exp": expires}, settings.secret_key,
                       algorithm="HS256")
    # httpOnly: page scripts can't read it; SameSite=Lax: other sites can't send it with their requests.
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=settings.cookie_secure,
                        max_age=settings.session_days * 86400, path="/")


def current_user(request: Request) -> User:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not logged in.")
    try:
        claims = jwt.decode(token, request.app.state.settings.secret_key, algorithms=["HS256"])
        user_id, version = int(claims["sub"]), int(claims.get("ver", 0))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired; log in again.")
    with session(request.app.state.engine) as db:
        user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found.")
    if version != (user.session_version or 0):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "The password was changed; log in again.")
    return user


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserOut)
def register(body: Registration, request: Request, response: Response):
    settings = request.app.state.settings
    if not settings.allow_signup:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign-up is closed; ask an administrator for an account.")
    _check_email_allowed(settings, body.email)
    _check_password(body.password)
    with session(request.app.state.engine) as db:
        if db.exec(select(User).where(User.email == body.email)).first():
            raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")
        user = User(email=body.email, password_hash=hasher.hash(body.password), name=body.name.strip()[:120] or None)
        db.add(user)
        db.commit()
        db.refresh(user)
    _set_session(response, request, user)
    return UserOut.of(user)


@router.post("/login", response_model=UserOut)
def login(body: Credentials, request: Request, response: Response):
    with session(request.app.state.engine) as db:
        user = db.exec(select(User).where(User.email == body.email)).first()
    valid = hasher.verify(body.password, user.password_hash if user else _DUMMY_HASH)
    if not (user and valid):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password.")
    _set_session(response, request, user)
    return UserOut.of(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return UserOut.of(user)


@router.patch("/me", response_model=UserOut)
def update_me(body: ProfileUpdate, request: Request, user: User = Depends(current_user)):
    with session(request.app.state.engine) as db:
        if body.email != user.email:
            _check_email_allowed(request.app.state.settings, body.email)
            if db.exec(select(User).where(User.email == body.email)).first():
                raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")
        user = db.get(User, user.id)
        user.name, user.email = body.name.strip()[:120] or None, body.email
        db.add(user)
        db.commit()
    return UserOut.of(user)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: PasswordChange, request: Request, response: Response, user: User = Depends(current_user)):
    if not hasher.verify(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The current password is wrong.")
    _check_password(body.new_password)
    with session(request.app.state.engine) as db:
        user = db.get(User, user.id)
        user.password_hash = hasher.hash(body.new_password)
        user.session_version = (user.session_version or 0) + 1  # other sessions end
        db.add(user)
        db.commit()
    _set_session(response, request, user)  # this one continues
