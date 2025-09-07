"""
Domínio RAG (Retrieval-Augmented Generation).

- Mantém o prompt BASE original como padrão.
- Melhora com: dedupe, filtro por score, orçamento de contexto por tokens,
  short-circuit, estilos opcionais (audit-bullets, concise, qa, verdict, compare,
  table, json, procedure, exec-summary, mitre-card), busca "hybrid" opcional,
  e limite adicional por caracteres no contexto.
- Limite de tokens SÓ da resposta (answer_max_tokens -> -n no llama.cpp).

Este módulo NÃO conhece FastAPI nem HTTP — apenas lógica de domínio.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol
import hashlib
import re


class RetrieverPort(Protocol):
    def search_knn_slim(self, query: str, top_k: int = 5) -> List[Dict]:
        """
        Retorna lista de trechos no formato:
        [{"id": str, "score": float, "text": str, "meta": dict}, ...]
        """
        ...



class GeneratorPort(Protocol):
    async def generate_response_async(self, prompt: str, max_tokens: int = 200) -> str:
        """Gera texto a partir de um prompt (assíncrono)."""
        ...


@dataclass(frozen=True)
class Citation:
    id: Optional[str]
    score: Optional[float]
    text: str
    meta: Optional[dict]


@dataclass
class RagRequest:
    question: str
    top_k: int = 3
    answer_max_tokens: Optional[int] = None
    max_tokens: Optional[int] = None
    style: Optional[str] = None
    search_mode: Optional[str] = None
    max_context_chars: Optional[int] = None


@dataclass(frozen=True)
class RagResponse:
    answer: str
    citations: List[Citation]


@dataclass(frozen=True)
class RagSettings:
    """
    Parâmetros de qualidade / políticas do domínio.
    """
    system_prompt_base: str = (
        "Você é um assistente que responde de forma detalhada e baseada na base de dados.\n"
        "Se a resposta não estiver nos trechos, diga claramente que não encontrou com base no contexto.\n"
        "Responda em português do Brasil.\n"
    )

    system_prompt_strict: str = (
        "Você é um assistente que responde os detalhes ESTRITAMENTE com base nos trechos fornecidos.\n"
        "Se a informação não estiver clara nos trechos, diga que NÃO encontrou com base no contexto.\n"
        "Inclua marcações [1], [2], ... para referenciar os trechos usados quando aplicável.\n"
        "Responda em português do Brasil.\n"
    )

    min_citations_to_answer: int = 1
    min_score: Optional[float] = None
    dedupe: bool = True
    short_circuit_on_empty: bool = True
    fallback_answer: str = (
        "Não encontrei informação suficiente nos trechos recuperados para responder com confiança."
    )
    ensure_citations_in_output: bool = False

    ctx_size: int = 4096
    reserve_tokens: int = 64
    chars_per_token: float = 4.0  # ~3–4 para PT

    max_context_chars: int = 16000


_WS_RE = re.compile(r"\s+")
_CITATION_TAG_RE = re.compile(r"\[\s*\d+\s*\]")
_NO_DISPONIBLE = "(nenhum trecho disponível)"


def _normalize_text(t: str) -> str:
    t = (t or "").strip()
    t = _WS_RE.sub(" ", t)
    return t


def _hash_text(t: str) -> str:
    return hashlib.sha256(_normalize_text(t).encode("utf-8", errors="ignore")).hexdigest()


def _dedupe_citations(citations: List[Citation]) -> List[Citation]:
    seen = set()
    out: List[Citation] = []
    for c in citations:
        h = _hash_text(c.text)
        if h in seen:
            continue
        seen.add(h)
        out.append(c)
    return out


def _apply_score_filter(citations: List[Citation], min_score: Optional[float]) -> List[Citation]:
    if min_score is None:
        return citations
    return [c for c in citations if (c.score is not None and c.score >= min_score)]


def _estimate_tokens(s: str, cpt: float) -> int:
    return max(1, int(len(s) / max(1e-6, cpt)))


def _pack_by_token_budget(citations: List[Citation], max_tokens: int, cpt: float) -> List[Citation]:
    """
    Inclui trechos na ordem até atingir o orçamento de tokens.
    Soma uma pequena margem a cada trecho para formatação.
    """
    if max_tokens <= 0:
        return citations[:1] if citations else []
    acc: List[Citation] = []
    used = 0
    for c in citations:
        need = _estimate_tokens(c.text, cpt) + 8  # margem por formatação
        if acc and used + need > max_tokens:
            break
        acc.append(c)
        used += need
        if used >= max_tokens:
            break
    if not acc and citations:
        acc = [citations[0]]
    return acc


def _truncate_by_char_budget(citations: List[Citation], max_chars: int) -> List[Citation]:
    """
    Limita o total de caracteres do bloco de contexto, preservando a ordem.
    Corta o último trecho se necessário.
    """
    if max_chars is None or max_chars <= 0:
        return citations
    out: List[Citation] = []
    total = 0
    for c in citations:
        txt = c.text or ""
        if not txt:
            continue
        if total + len(txt) <= max_chars:
            out.append(c)
            total += len(txt)
        else:
            remaining = max_chars - total
            if remaining > 50:
                clipped = txt[: remaining - 3].rstrip() + "..."
                out.append(Citation(id=c.id, score=c.score, text=clipped, meta=c.meta))
            break
    return out


def _render_context_block(citations: List[Citation]) -> str:
    lines = []
    for i, c in enumerate(citations, start=1):
        meta_str = ""
        if c.meta:
            src = (
                c.meta.get("url")
                or c.meta.get("source")
                or c.meta.get("id")
                or c.id
            )
            if src:
                meta_str = f"\nFonte: {src}"
        lines.append(f"[{i}] {c.text}{meta_str}")
    return "\n\n".join(lines)


def build_prompt_base(question: str, citations: List[Citation], s: RagSettings) -> str:
    """
    Seu prompt original como DEFAULT.
    """
    if not citations:
        return (
            f"{s.system_prompt_base}\n"
            f"# Pergunta\n{question}\n\n"
            "# Trechos\n(nenhum trecho disponível)\n\n"
            "# Resposta:"
        )
    ctx = "\n\n".join(f"[{i + 1}] {c.text}" for i, c in enumerate(citations))
    return (
        f"{s.system_prompt_base}\n"
        f"# Pergunta\n{question}\n\n"
        f"# Trechos\n{ctx}\n\n"
        "# Resposta:"
    )


def build_prompt_audit_bullets(question: str, citations: List[Citation], s: RagSettings) -> str:
    header = (
        s.system_prompt_strict +
        "Formate como uma lista de tópicos curtos e verificáveis. "
        "Cada afirmação importante deve terminar com [n].\n"
    )
    if not citations:
        return (
            f"{header}\n"
            f"# Pergunta\n{question}\n\n"
            "# Trechos\n(nenhum trecho disponível)\n\n"
            "# Resposta (bullets curtos; diga que não encontrou se não houver base):"
        )
    ctx = _render_context_block(citations)
    return (
        f"{header}\n"
        f"# Pergunta\n{question}\n\n"
        f"# Trechos (use [n])\n{ctx}\n\n"
        "# Resposta (cada linha com [n]):"
    )


def build_prompt_concise(question: str, citations: List[Citation], s: RagSettings) -> str:
    ctx = _render_context_block(citations) if citations else _NO_DISPONIBLE
    return (
        s.system_prompt_strict +
        "Responda de forma concisa em 3–6 bullets; cada linha deve terminar com [n].\n\n"
        f"# Pergunta\n{question}\n\n# Trechos\n{ctx}\n\n# Resposta:"
    )


def build_prompt_qa(question: str, citations: List[Citation], s: RagSettings) -> str:
    ctx = _render_context_block(citations) if citations else _NO_DISPONIBLE
    return (
        s.system_prompt_strict +
        "Forneça primeiro uma RESPOSTA DIRETA (1–2 frases). Depois, DETALHES em bullets com [n].\n\n"
        f"# Pergunta\n{question}\n\n# Trechos (use [n])\n{ctx}\n\n"
        "# Resposta direta:\n\n# Detalhes:\n- "
    )


def build_prompt_verdict(question: str, citations: List[Citation], s: RagSettings) -> str:
    ctx = _render_context_block(citations) if citations else _NO_DISPONIBLE
    return (
        s.system_prompt_strict +
        "Responda com um VEREDITO (Sim/Não/Parcial) em uma linha, seguido de justificativa curta com [n].\n\n"
        f"# Pergunta\n{question}\n\n# Trechos (use [n])\n{ctx}\n\n"
        "# Resposta:\nVeredicto: ...\nJustificativa: ... [n]"
    )


def build_prompt_compare(question: str, citations: List[Citation], s: RagSettings) -> str:
    ctx = _render_context_block(citations) if citations else _NO_DISPONIBLE
    return (
        s.system_prompt_strict +
        "Produza uma TABELA Markdown comparando itens. Colunas: Item | Evidência [n] | Observações.\n\n"
        f"# Pergunta\n{question}\n\n# Trechos (use [n])\n{ctx}\n\n"
        "# Resposta (tabela Markdown):\n| Item | Evidência | Observações |\n|---|---|---|\n"
    )


def build_prompt_table(question: str, citations: List[Citation], s: RagSettings) -> str:
    ctx = _render_context_block(citations) if citations else _NO_DISPONIBLE
    return (
        s.system_prompt_strict +
        "Resuma em uma TABELA Markdown. Colunas: Campo | Conteúdo | Fonte [n].\n\n"
        f"# Pergunta\n{question}\n\n# Trechos (use [n])\n{ctx}\n\n"
        "# Resposta (tabela Markdown):\n| Campo | Conteúdo | Fonte |\n|---|---|---|\n"
    )


def build_prompt_json(question: str, citations: List[Citation], s: RagSettings) -> str:
    ctx = _render_context_block(citations) if citations else _NO_DISPONIBLE
    return (
        s.system_prompt_strict +
        "Retorne estritamente um JSON válido com as chaves: "
        "`answer` (string), `bullets` (array de strings), `citations_used` (array de ints). "
        "Cada bullet deve conter [n]. Não retorne nada fora do JSON.\n\n"
        f"# Pergunta\n{question}\n\n# Trechos (use [n])\n{ctx}\n\n"
        "# Resposta (apenas JSON):"
    )


def build_prompt_procedure(question: str, citations: List[Citation], s: RagSettings) -> str:
    ctx = _render_context_block(citations) if citations else _NO_DISPONIBLE
    return (
        s.system_prompt_strict +
        "Forneça um PROCEDIMENTO em passos numerados (1–5), cada passo ancorado em [n].\n\n"
        f"# Pergunta\n{question}\n\n# Trechos (use [n])\n{ctx}\n\n"
        "# Resposta:\n1) ... [n]\n2) ... [n]"
    )


def build_prompt_exec_summary(question: str, citations: List[Citation], s: RagSettings) -> str:
    ctx = _render_context_block(citations) if citations else _NO_DISPONIBLE
    return (
        s.system_prompt_strict +
        "Produza um RESUMO EXECUTIVO (3 bullets), depois RISCOS (até 3), e LACUNAS (até 2). Tudo com [n].\n\n"
        f"# Pergunta\n{question}\n\n# Trechos (use [n])\n{ctx}\n\n"
        "# Resumo executivo:\n- ... [n]\n- ... [n]\n- ... [n]\n\n# Riscos:\n- ... [n]\n\n# Lacunas:\n- ... [n]"
    )


def build_prompt_mitre_card(question: str, citations: List[Citation], s: RagSettings) -> str:
    ctx = _render_context_block(citations) if citations else _NO_DISPONIBLE
    return (
        s.system_prompt_strict +
        "Formate como um cartão MITRE ATT&CK (mobile): Tática(s), Técnica/Subtécnica, Plataformas, "
        "Mitigações, Detecções, Referências. Cada afirmação com [n].\n\n"
        f"# Pergunta\n{question}\n\n# Trechos (use [n])\n{ctx}\n\n"
        "# Resposta (cartão):\n"
        "## Tática(s):\n- ... [n]\n\n"
        "## Técnica/Subtécnica:\n- ... [n]\n\n"
        "## Plataformas:\n- ... [n]\n\n"
        "## Mitigações:\n- ... [n]\n\n"
        "## Detecções:\n- ... [n]\n\n"
        "## Referências:\n- ... [n]"
    )


def build_prompt(question: str, citations: List[Citation], s: RagSettings, style: Optional[str]) -> str:
    key = (style or "base").lower()
    if key == "base":
        return build_prompt_base(question, citations, s)
    if key == "audit-bullets":
        return build_prompt_audit_bullets(question, citations, s)
    if key == "concise":
        return build_prompt_concise(question, citations, s)
    if key == "qa":
        return build_prompt_qa(question, citations, s)
    # if key == "verdict":
    #     return build_prompt_verdict(question, citations, s)
    if key == "compare":
        return build_prompt_compare(question, citations, s)
    if key == "table":
        return build_prompt_table(question, citations, s)
    if key == "json":
        return build_prompt_json(question, citations, s)
    # if key == "procedure":
    #     return build_prompt_procedure(question, citations, s)
    # if key == "exec-summary":
    #     return build_prompt_exec_summary(question, citations, s)
    if key == "mitre-card":
        return build_prompt_mitre_card(question, citations, s)
    return build_prompt_base(question, citations, s)


class RagDomain:
    """
    Caso de uso principal: responder perguntas com RAG.
    """

    def __init__(
        self,
        retriever: RetrieverPort,
        generator: GeneratorPort,
        settings: Optional[RagSettings] = None,
    ) -> None:
        self.retriever = retriever
        self.generator = generator
        self.settings = settings or RagSettings()

    async def ask(self, req: RagRequest) -> RagResponse:
        """
        Fluxo:
        1) Recupera 'top_k' trechos (KNN ou HYBRID se disponível e solicitado).
        2) Dedup / filtro por score.
        3) Orçamento de contexto por tokens + limite adicional por caracteres.
        4) Short-circuit se faltar contexto (opcional).
        5) Constrói prompt (preset opcional) e chama LLM com limite de RESPOSTA.
        6) Guard-rails opcionais.
        """
        mode = (req.search_mode or "knn").strip().lower()
        if mode == "hybrid" and hasattr(self.retriever, "search_hybrid_slim"):
            raw_hits = getattr(self.retriever, "search_hybrid_slim")(req.question, top_k=req.top_k) or []
        else:
            raw_hits = self.retriever.search_knn_slim(req.question, top_k=req.top_k) or []

        citations = [
            Citation(
                id=h.get("id"),
                score=h.get("score"),
                text=_normalize_text(h.get("text", "")),
                meta=(h.get("meta") or {}),
            )
            for h in raw_hits
            if h.get("text")
        ]

        if self.settings.dedupe:
            citations = _dedupe_citations(citations)
        citations = _apply_score_filter(citations, self.settings.min_score)

        answer_max = (
            req.answer_max_tokens
            if req.answer_max_tokens is not None
            else (req.max_tokens if req.max_tokens is not None else 400)
        )
        try:
            answer_max_int = int(answer_max)
        except Exception:
            answer_max_int = 400
        answer_max_int = max(64, min(answer_max_int, 2000))

        question_tokens = _estimate_tokens(req.question, self.settings.chars_per_token)
        available_ctx_tokens = max(
            128,
            self.settings.ctx_size - answer_max_int - self.settings.reserve_tokens - question_tokens
        )
        citations = _pack_by_token_budget(citations, available_ctx_tokens, self.settings.chars_per_token)

        char_cap = req.max_context_chars if (req.max_context_chars is not None) else self.settings.max_context_chars
        citations = _truncate_by_char_budget(citations, char_cap)

        if len(citations) < self.settings.min_citations_to_answer and self.settings.short_circuit_on_empty:
            return RagResponse(answer=self.settings.fallback_answer, citations=citations)

        prompt = build_prompt(req.question, citations, self.settings, req.style)
        try:
            answer = await self.generator.generate_response_async(
                prompt=prompt,
                max_tokens=answer_max_int,
            )
            answer = (answer or "").strip()
        except Exception as e:
            answer = f"{self.settings.fallback_answer} (erro do gerador: {e})"

        if not answer:
            answer = self.settings.fallback_answer

        if self.settings.ensure_citations_in_output and citations and not _CITATION_TAG_RE.search(answer):
            answer = answer + "\n\nObservação: inclua referências [n] na próxima resposta."

        return RagResponse(answer=answer, citations=citations)
