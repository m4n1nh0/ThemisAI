"""
Módulo de segurança para FastAPI.
Fornece a dependência 'get_current_user' que:
- Lê o token JWT do header Authorization (Bearer).
- Decodifica e valida o token.
- Retorna o usuário autenticado.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.domain.auth_domain import auth_domain
from app.db.dto.user_dto import UserDTO

security = HTTPBearer(auto_error=False)
repo = UserDTO()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """
    Dependency que valida o token e retorna o usuário autenticado.

    - 'credentials': Extraído automaticamente do header Authorization.
    - 'return': Usuário (dict) recuperado do banco.

    - raise: HTTP 401 se:
        * header ausente ou malformado
        * token inválido/expirado
        * usuário não existir mais no banco
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
        )

    token = credentials.credentials
    payload = auth_domain.decode_token(token)

    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = repo.get_by_username(username)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user
