"""
Módulo de conexão SQLite para autenticação de usuários.
Indicado para desenvolvimento / PoC.
Em produção prefira um banco robusto (Postgres, MySQL).
"""

import sqlite3
from pathlib import Path

DB_PATH = Path("users.db")

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row


def init_db() -> None:
    """
    Inicializa o schema de usuários no SQLite.

    Cria a tabela 'users' e índice único para 'username'
    se ainda não existirem.
    """
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);"
    )
    conn.commit()


init_db()
