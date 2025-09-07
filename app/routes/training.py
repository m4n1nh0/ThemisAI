"""
Rotas de treinamento/ingestão de conhecimento no OpenSearch.

- Protegida por Bearer Token (HTTP Authorization).
- Suporta:
  1) texts: Lista simples de strings.
  2) docs: Lista de objetos {id?, text, metadata?} com chunking configurável.
- Preserva metadados legíveis no chunking para “Fonte” nos prompts.
"""

from __future__ import annotations
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.config.security import get_current_user
from app.services.opensearch_service import (
    OpenSearchService,
    get_opensearch_service,
)

router = APIRouter(prefix="/training", tags=["training"])


class TrainDoc(BaseModel):
    """Documento individual para ingestão."""
    id: Optional[str] = None
    text: str = Field(..., min_length=1)
    metadata: Optional[Dict[str, Any]] = None


class TrainRequest(BaseModel):
    """
    Requisição de ingestão.

    Use UM dos campos a seguir (ou ambos):
    - texts: lista simples de strings (serão indexadas como documentos sem metadata)
    - docs: lista de objetos com metadata e chunking

    Parâmetros de chunking (aplicáveis apenas a 'docs'):
    - chunk_size: tamanho máximo de cada pedaço
    - chunk_overlap: sobreposição entre pedaços consecutivos
    """
    texts: Optional[List[str]] = None
    docs: Optional[List[TrainDoc]] = None
    chunk_size: int = 800
    chunk_overlap: int = 100


@router.post("/train")
async def train(
    req: TrainRequest,
    _user: dict = Depends(get_current_user),  # Protege a rota
    osvc: OpenSearchService = Depends(get_opensearch_service),
):
    """
    Ingere conhecimento no índice padrão do OpenSearch.

    - Aceita 'texts' simples OU 'docs' com metadata e chunking.
    - Retorna contagem de itens recebidos e indexados.
    """
    has_texts = bool(req.texts and any((t or "").strip() for t in req.texts))
    has_docs = bool(req.docs)

    if not has_texts and not has_docs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Envie ao menos 'texts' ou 'docs'.",
        )

    to_index: List[Dict[str, Any]] = []

    # 1) Ingestão simples (texts)
    if has_texts:
        for t in req.texts or []:
            t = (t or "").strip()
            if not t:
                continue
            to_index.append({"text": t, "metadata": {}})

    if has_docs:
        step = max(req.chunk_size - req.chunk_overlap, 1)
        for d in req.docs or []:
            text = (d.text or "").strip()
            if not text:
                continue

            base_meta = d.metadata or {}
            source_id = base_meta.get("attack_id") or d.id
            source_name = base_meta.get("name")
            first_url = base_meta.get("url") or (base_meta.get("urls") or [None])[0]

            if len(text) <= req.chunk_size:
                meta = {
                    **base_meta,
                    "source_id": source_id,
                    "source_name": source_name,
                    "url": first_url,
                    "chunk_of": d.id or source_id,
                    "chunk_index": 0,
                    "is_chunk": False,
                }
                to_index.append({"id": d.id, "text": text, "metadata": meta})
                continue

            part = 0
            for i in range(0, len(text), step):
                chunk = text[i: i + req.chunk_size]
                if not chunk:
                    continue
                chunk_id = f"{d.id or source_id}::{part}"
                meta = {
                    **base_meta,
                    "source_id": source_id,
                    "source_name": source_name,
                    "url": first_url,
                    "chunk_of": d.id or source_id,
                    "chunk_index": part,
                    "is_chunk": True,
                }
                to_index.append({"id": chunk_id, "text": chunk, "metadata": meta})
                part += 1

    try:
        res = osvc.index_docs(to_index)
        return {
            "ok": True,
            "received": {"texts": len(req.texts or []), "docs": len(req.docs or [])},
            "prepared_for_index": len(to_index),
            "indexed": res.get("indexed", 0),
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao indexar documentos: {e}",
        )
