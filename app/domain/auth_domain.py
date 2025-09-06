"""
Serviço de Autenticação (hash de senha + JWT com PyJWT).

- Depende do UserRepository para persistência (SQLite).
- Fornece funções para:
  - hash e verificação de senha
  - criação e decodificação de JWT
  - registro e autenticação de usuário
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import jwt
from jwt import PyJWTError
from fastapi import HTTPException, status
from passlib.context import CryptContext

from app.config.settings import settings
from app.db.dto.user_dto import UserDTO


def _utcnow() -> datetime:
    """Retorna datetime atual em UTC (timezone-aware)."""
    return datetime.now(timezone.utc)


class AuthDomain:
    """
    Serviço de autenticação.

    Métodos principais:
    - 'hash_password(password: str) -> str'
    - 'verify_password(plain_password: str, hashed_password: str) -> bool'
    - 'create_access_token(data: dict, expires_delta: timedelta) -> str'
    - 'decode_token(token: str) -> dict'
    - 'authenticate_user(username: str, password: str) -> Optional[dict]'
    - 'register_user(username: str, password: str) -> dict'
    """

    def __init__(self, repo: Optional[UserDTO] = None) -> None:
        self.repo = repo or UserDTO()
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    def hash_password(self, password: str) -> str:
        """
        Gera hash seguro para a senha.

        - 'password': Senha em texto plano
        - return: Hash (bcrypt)
        """
        return self.pwd_context.hash(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """
        Verifica senha em texto plano contra o hash armazenado.

        - 'plain_password': Senha em texto
        - 'hashed_password': Hash armazenado
        - return: True se confere; False caso contrário
        """
        return self.pwd_context.verify(plain_password, hashed_password)

    def create_access_token(self, data: Dict[str, Any], expires_delta: timedelta) -> str:
        """
        Cria um token JWT assinado (HS256 por padrão).

        - 'data': Claims (ex.: {"sub": "<username>"})
        - 'expires_delta': Tempo até expiração do token
        - return: Token JWT
        """
        to_encode = data.copy()
        expire = _utcnow() + expires_delta
        to_encode.update({"exp": expire})
        token = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        return token

    def decode_token(self, token: str) -> Dict[str, Any]:
        """
        Decodifica e valida um JWT.

        - 'token': JWT recebido no Authorization Bearer
        - return: Claims decodificadas
        - raise: HTTPException 401 se inválido/expirado
        """
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            return payload
        except PyJWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )

    def authenticate_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """
        Autentica um usuário verificando a senha.

        - 'username': Nome do usuário
        - 'password': Senha em texto
        - return: Dict do usuário se autenticado; None caso contrário
        """
        user = self.repo.get_by_username(username)
        if user and self.verify_password(password, user["password"]):
            return user
        return None

    def register_user(self, username: str, password: str) -> Dict[str, Any]:
        """
        Registra um novo usuário (verifica duplicidade e salva hash).

        - 'username': Nome único do usuário
        - 'password': Senha em texto
        - return: Mensagem de sucesso
        - raise: HTTP 400 se username já existir
        """
        if self.repo.get_by_username(username):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already exists")
        hashed = self.hash_password(password)
        created_at = _utcnow().isoformat()
        return self.repo.create_user(username, hashed, created_at)


auth_domain = AuthDomain()
