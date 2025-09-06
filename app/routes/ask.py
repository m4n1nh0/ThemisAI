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
from typing import List

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
    """
    question: str = Field(..., min_length=2)
    top_k: int = 3
    max_tokens: int = 200


class ApiCitation(BaseModel):
    id: str | None = None
    score: float | None = None
    text: str
    meta: dict | None = None


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
        rag_resp: RagResponse = await domain.ask(
            RagRequest(
                question=req.question,
                top_k=req.top_k,
                max_tokens=req.max_tokens,
            )
        )
        return AskResponse(
            answer=rag_resp.answer,
            citations=[ApiCitation(**c.__dict__) for c in rag_resp.citations],
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao gerar resposta: {e}",
        )
