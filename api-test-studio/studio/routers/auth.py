import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from .. import config
from ..db import get_db
from ..deps import SESSION_COOKIE, current_user
from ..models import AuthSession, User
from ..security import auth_limiter, hash_password, new_token, token_hash, verify_password

router = APIRouter(prefix='/api/auth', tags=['Authentication'])

EMAIL_PATTERN = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'


class RegisterInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=254, pattern=EMAIL_PATTERN)
    password: str = Field(min_length=8, max_length=200)


class LoginInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


def user_json(user: User) -> dict:
    return {'id': user.id, 'name': user.name, 'email': user.email}


def start_session(db: DbSession, response: Response, user: User):
    token = new_token()
    db.add(AuthSession(token_hash=token_hash(token), user_id=user.id, kind='browser',
                       expires_at=time.time() + config.SESSION_SECONDS))
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite='strict',
                        secure=config.COOKIE_SECURE, max_age=config.SESSION_SECONDS)


def client_key(request: Request) -> str:
    return request.client.host if request.client else 'unknown'


@router.post('/register')
def register(body: RegisterInput, request: Request, response: Response, db: DbSession = Depends(get_db)):
    auth_limiter.check(client_key(request))
    email = body.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, 'An account with this email already exists. Sign in instead.')
    user = User(name=body.name.strip(), email=email, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    start_session(db, response, user)
    db.commit()
    return user_json(user)


@router.post('/login')
def login(body: LoginInput, request: Request, response: Response, db: DbSession = Depends(get_db)):
    auth_limiter.check(client_key(request))
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, 'Email or password is incorrect.')
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id, AuthSession.kind == 'browser',
                                         AuthSession.expires_at < time.time()))
    start_session(db, response, user)
    db.commit()
    return user_json(user)


@router.post('/logout')
def logout(request: Request, response: Response, db: DbSession = Depends(get_db), user: User = Depends(current_user)):
    token = request.cookies.get(SESSION_COOKIE, '')
    db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(token)))
    db.commit()
    response.delete_cookie(SESSION_COOKIE)
    return {'ok': True}


@router.get('/me')
def me(user: User = Depends(current_user)):
    return user_json(user)
