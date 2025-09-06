"""
Domínio RAG (Retrieval-Augmented Generation).

Regras de negócio puras:
- Montagem de prompt com base em trechos recuperados (citations).
- Orquestração entre busca (OpenSearch) e geração (LLaMA).
- Política de fallback quando não há contexto suficiente.

Este módulo NÃO conhece FastAPI nem HTTP — apenas lógica de domínio.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Protocol


class RetrieverPort(Protocol):
    """Porta para um recuperador de contexto (ex.: OpenSearch)."""

    def search_knn_slim(self, query: str, top_k: int = 5) -> List[Dict]:
        """
        Retorna lista de trechos no formato:
        [{"id": str, "score": float, "text": str, "meta": dict}, ...]
        """
        ...


class GeneratorPort(Protocol):
    """Porta para um gerador de texto (ex.: LLaMA)."""

    async def generate_response_async(self, prompt: str, max_tokens: int = 200) -> str:  # noqa: D401
        """
        Gera texto a partir de um prompt (assíncrono).
        """
        ...


@dataclass(frozen=True)
class Citation:
    id: str | None
    score: float | None
    text: str
    meta: dict | None


@dataclass(frozen=True)
class RagRequest:
    question: str
    top_k: int = 3
    max_tokens: int = 200


@dataclass(frozen=True)
class RagResponse:
    answer: str
    citations: List[Citation]


_SYSTEM_PROMPT = (
    "Você é um assistente que responde de forma detalhada e baseada na base de dados.\n"
    "Se a resposta não estiver nos trechos, diga claramente que não encontrou com base no contexto.\n"
    "Responda em português do Brasil.\n"
)


def build_prompt(question: str, citations: List[Citation]) -> str:
    """
    Constrói o prompt a partir da pergunta e dos trechos recuperados.

    - 'question': Pergunta do usuário
    - 'citations': Lista de trechos contextualizados
    - 'return': Prompt consolidado para o gerador
    """
    if not citations:
        return (
            f"{_SYSTEM_PROMPT}\n"
            f"# Pergunta\n{question}\n\n"
            "# Trechos\n(nenhum trecho disponível)\n\n"
            "# Resposta:"
        )

    ctx = "\n\n".join(f"[{i+1}] {c.text}" for i, c in enumerate(citations))
    return (
        f"{_SYSTEM_PROMPT}\n"
        f"# Pergunta\n{question}\n\n"
        f"# Trechos\n{ctx}\n\n"
        "# Resposta:"
    )


class RagDomain:
    """
    Caso de uso principal: responder perguntas com RAG.

    - Depende de portas (RetrieverPort, GeneratorPort) para facilitar testes.
    - Aplica regras de negócio: recuperar → montar prompt → gerar resposta.
    """

    def __init__(self, retriever: RetrieverPort, generator: GeneratorPort) -> None:
        self.retriever = retriever
        self.generator = generator

    async def ask(self, req: RagRequest) -> RagResponse:
        """
        Executa o fluxo RAG completo:

        1) Recupera 'top_k' trechos.
        2) Constrói o prompt com as citações.
        3) Gera resposta com o modelo LLM.
        4) Retorna resposta + citações.

        - 'req': Parâmetros da pergunta
        - 'return': 'RagResponse'
        """
        hits = self.retriever.search_knn_slim(req.question, top_k=req.top_k)
        citations = [
            Citation(
                id=h.get("id"),
                score=h.get("score"),
                text=h.get("text", ""),
                meta=h.get("meta") or {},
            )
            for h in hits
        ]

        prompt = build_prompt(req.question, citations)
        answer = await self.generator.generate_response_async(prompt, max_tokens=req.max_tokens)
        return RagResponse(answer=answer, citations=citations)
