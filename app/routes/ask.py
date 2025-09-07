"""
Rotas de perguntas (RAG: Retrieval-Augmented Generation).

Fluxo:
1) Usuário pergunta (payload).
2) Recuperamos contexto no OpenSearch (RetrieverPort).
3) Montamos prompt e geramos resposta com LLaMA (GeneratorPort).
4) Retornamos resposta + citações.

Protegido por Bearer Token (HTTP Authorization).
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.config.security import get_current_user
from app.domain import RagDomain, RagRequest, RagResponse, Citation
from app.services.opensearch_service import OpenSearchService
from app.services.llama_service import LlamaService

router = APIRouter(prefix="/ask", tags=["ask"])


class AskRequest(BaseModel):
    """
    Payload de pergunta ao sistema RAG.

    Campos:
      - question: pergunta do usuário
      - top_k: quantos trechos recuperar
      - max_tokens: (LEGADO) se enviado, será usado como fallback para answer_max_tokens
      - answer_max_tokens: limite de tokens da RESPOSTA (recomendado)
      - style: preset de estilo ("paragraph"|"audit-bullets"|"json-compact"|"qa-strict")
      - search_mode: "knn" (padrão) ou "hybrid" se seu retriever suportar
      - max_context_chars: limite de caracteres agregados do CONTEXTO (trechos)
    """
    question: str = Field(..., min_length=2)
    top_k: int = 3
    max_tokens: Optional[int] = None
    answer_max_tokens: Optional[int] = None
    style: Optional[str] = None
    search_mode: Optional[str] = None
    max_context_chars: int = 16000


class ApiCitation(BaseModel):
    id: Optional[str] = None
    score: Optional[float] = None
    text: str
    meta: Optional[dict] = None


class AskResponse(BaseModel):
    answer: str
    citations: List[ApiCitation] = []


def get_rag_domain() -> RagDomain:
    retriever = OpenSearchService()
    generator = LlamaService()
    return RagDomain(retriever=retriever, generator=generator)


@router.post("/question", response_model=AskResponse)
async def ask_question(
    req: AskRequest,
    _user: dict = Depends(get_current_user),
    domain: RagDomain = Depends(get_rag_domain),
):
    try:
        rag_req = RagRequest(
            question=req.question,
            top_k=req.top_k,
            max_tokens=req.max_tokens,                    # compat
            answer_max_tokens=req.answer_max_tokens,      # recomendado
            style=req.style,
            search_mode=req.search_mode,
            max_context_chars=req.max_context_chars,
        )
        rag_resp: RagResponse = await domain.ask(rag_req)

        return AskResponse(
            answer=rag_resp.answer,
            citations=[ApiCitation(**c.__dict__) for c in rag_resp.citations],
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao gerar resposta: {e}",
        )
