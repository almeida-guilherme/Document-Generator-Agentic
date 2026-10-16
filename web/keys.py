"""
People's own API keys ("bring your own key"): each project runs on the key its owner picks, so usage is
billed to them. Keys are encrypted in the database with a key derived from the server's secret
(PDD_SECRET_KEY) and never sent back to the browser; only their last four characters are shown.
The server's own key (OPENAI_API_KEY in .env) can be offered too, as "the server key".
"""
import base64
import hashlib
import os
from datetime import datetime
from typing import Literal
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlmodel import select

from web.auth import current_user
from web.db import ApiKey, User, session

router = APIRouter(prefix="/api/keys", tags=["api keys"])

# The pipeline calls OpenAI (vision captions, Whisper, structuring), so only OpenAI keys can run it.
PROVIDERS = {"openai": "OpenAI"}


class KeyOut(BaseModel):
    id: str
    provider: str
    name: str
    hint: str  # e.g. "sk-…4F2a"
    created_at: datetime


class KeysOut(BaseModel):
    keys: list[KeyOut]
    server_key: bool  # whether projects can run on the server's own key


class NewKey(BaseModel):
    provider: Literal["openai"] = "openai"
    name: str
    key: str


def _fernet(secret: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"pdd-api-keys:" + secret.encode()).digest()))


def encrypt(secret: str, key: str) -> str:
    return _fernet(secret).encrypt(key.encode()).decode()


def decrypt(secret: str, token: str) -> str:
    try:
        return _fernet(secret).decrypt(token.encode()).decode()
    except InvalidToken:
        # The server's secret changed since the key was saved.
        raise ValueError("This API key can no longer be read; remove it and connect it again.")


def server_key_available(request: Request) -> bool:
    return request.app.state.settings.allow_server_key and bool(os.getenv("OPENAI_API_KEY"))


def check_openai_key(key: str) -> None:
    """Raises ValueError if OpenAI refuses the key. Listing models costs nothing."""
    import openai
    try:
        openai.OpenAI(api_key=key, timeout=15, max_retries=1).models.list()
    except openai.AuthenticationError:
        raise ValueError("OpenAI refused this key. Check that it was copied whole and is still active.")
    except openai.APIError as exc:
        raise ValueError(f"The key couldn't be checked with OpenAI ({type(exc).__name__}). Try again.")


def _out(key: ApiKey) -> KeyOut:
    return KeyOut(id=key.id, provider=key.provider, name=key.name, hint=f"{key.prefix}…{key.last4}",
                  created_at=key.created_at)


def user_key(request: Request, user: User, key_id: str) -> ApiKey:
    with session(request.app.state.engine) as db:
        key = db.get(ApiKey, key_id)
    if key is None or key.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found.")
    return key


def pick_key(request: Request, user: User, key_id: str | None) -> ApiKey | None:
    """
    The key work runs on: the user's chosen key; with none chosen, their newest key; None means the
    server's own key, which is used only when the user has no key of their own.
    """
    if key_id:
        return user_key(request, user, key_id)
    with session(request.app.state.engine) as db:
        key = db.exec(select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())).first()
    if key is None and not server_key_available(request):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Connect an API key in your account first.")
    return key


def key_value(request: Request, key: ApiKey | None) -> str | None:
    """The decrypted key, or None for the server's key."""
    if key is None:
        return None
    try:
        return decrypt(request.app.state.settings.secret_key, key.secret)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))


@router.get("", response_model=KeysOut)
def list_keys(request: Request, user: User = Depends(current_user)):
    with session(request.app.state.engine) as db:
        keys = db.exec(select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at)).all()
    return KeysOut(keys=[_out(k) for k in keys], server_key=server_key_available(request))


@router.post("", status_code=status.HTTP_201_CREATED, response_model=KeyOut)
def add_key(body: NewKey, request: Request, user: User = Depends(current_user)):
    key = body.key.strip()
    name = body.name.strip()[:60] or f"{PROVIDERS[body.provider]} key"
    if len(key) < 20 or any(c.isspace() for c in key):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That doesn't look like an API key.")
    try:
        request.app.state.check_api_key(key)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    record = ApiKey(user_id=user.id, provider=body.provider, name=name, prefix=key[:3], last4=key[-4:],
                    secret=encrypt(request.app.state.settings.secret_key, key))
    with session(request.app.state.engine) as db:
        db.add(record)
        db.commit()
    return _out(record)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_key(key_id: str, request: Request, user: User = Depends(current_user)):
    user_key(request, user, key_id)
    with session(request.app.state.engine) as db:
        db.delete(db.get(ApiKey, key_id))
        db.commit()
