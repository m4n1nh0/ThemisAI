"""
Rotas de autenticação (registro e login).
Usa AuthService (PyJWT + passlib[bcrypt]) e retorna JWT no login.
"""

from datetime import timedelta
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.domain.auth_domain import auth_domain

router = APIRouter(prefix="/auth", tags=["auth"])


class UserCreate(BaseModel):
    """
    Payload para registro.
    - `username`: Nome único (>=3)
    - `password`: Senha (>=6)
    """
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)


class UserLogin(BaseModel):
    """
    Payload para login.
    """
    username: str
    password: str


class TokenResponse(BaseModel):
    """
    Resposta de autenticação.
    """
    access_token: str
    token_type: str = "bearer"


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(user: UserCreate):
    """
    Registra um novo usuário.
    """
    created = auth_domain.register_user(user.username, user.password)
    if not created:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não foi possível registrar o usuário.",
        )
    return created


@router.post("/login", response_model=TokenResponse)
def login(user: UserLogin):
    """
    Faz login e retorna um JWT de acesso.
    """
    db_user = auth_domain.authenticate_user(user.username, user.password)
    if not db_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = auth_domain.create_access_token(
        {"sub": user.username},
        expires_delta=timedelta(minutes=30),
    )
    return TokenResponse(access_token=token)
