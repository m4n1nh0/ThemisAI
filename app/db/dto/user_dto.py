"""
Repositório de Usuários (SQLite).
Responsável por isolar o acesso ao banco (CRUD básico).
"""

from __future__ import annotations
from typing import Optional, Dict, Any

from app.db.sqlite import conn


class UserDTO:
    """
    Operações de acesso a dados para usuários.
    """

    def get_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """
        Busca um usuário pelo username.

        - username: Nome do usuário (único)
        - return: dict com colunas do usuário ou None
        """
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = ? LIMIT 1", (username,))
        row = cur.fetchone()
        return dict(row) if row else None

    def create_user(self, username: str, password_hashed: str, created_at_iso: str) -> Dict[str, Any]:
        """
        Cria um usuário.

        - username: Nome único
        - password_hashed: Senha já criptografada (bcrypt)
        - created_at_iso: Timestamp ISO-8601 (UTC)
        - return: dict com mensagem de sucesso
        """
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (username, password, created_at) VALUES (?, ?, ?)",
            (username, password_hashed, created_at_iso),
        )
        conn.commit()
        return {"message": "User registered successfully"}
