from pydantic import BaseModel, Field


class User(BaseModel):
    """
    Modelo de usuário.

    - 'username': Nome de usuário
    - 'password': Senha em texto (apenas para input)
    """
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)
