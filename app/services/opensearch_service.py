"""
Serviço de integração com OpenSearch para RAG.

Recursos:
- Cliente com timeouts e retries.
- Criação idempotente de índice com KNN (FAISS/HNSW).
- Indexação em lote (bulk) para performance.
- Busca KNN (hits brutos) e "slim" (id, score, text, meta).
- Busca híbrida opcional (BM25 + KNN) com RRF.
- Dimensão do embedding inferida do modelo Sentence-Transformers.

Compatível com docker-compose (ex.):
  OPENSEARCH_HOST=http://opensearch-node1:9200
"""

from __future__ import annotations

from itertools import islice
from typing import Any, Dict, Iterable, List, Optional, Tuple

from opensearchpy import OpenSearch, RequestsHttpConnection
from requests.auth import HTTPBasicAuth
from sentence_transformers import SentenceTransformer

from app.config.settings import settings


class OpenSearchService:
    """
    Serviço de acesso ao OpenSearch com suporte a embeddings e KNN.
    """

    def __init__(
        self,
        index_name: str | None = None,
        host: str | None = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        timeout: Optional[int] = None,
        embed_model_name: Optional[str] = None,
    ) -> None:
        self.index = index_name or settings.INDEX_NAME
        host = host or settings.OPENSEARCH_HOST
        user = user if user is not None else settings.OPENSEARCH_USER
        password = password if password is not None else settings.OPENSEARCH_PASS
        timeout = timeout or settings.OPENSEARCH_TIMEOUT
        embed_model_name = embed_model_name or settings.EMBED_MODEL_NAME

        use_ssl = str(host).startswith("https")
        http_auth = HTTPBasicAuth(user, password) if (user and password) else None
        self.client = OpenSearch(
            hosts=[host],
            http_auth=http_auth,
            use_ssl=use_ssl,
            verify_certs=False if use_ssl else False,
            ssl_show_warn=False,
            connection_class=RequestsHttpConnection,
            timeout=timeout,
            max_retries=3,
            retry_on_timeout=True,
        )

        self.embedding_model = SentenceTransformer(embed_model_name)
        self.embedding_dim = int(self.embedding_model.get_sentence_embedding_dimension())

        self.ensure_index()

    def ensure_index(self) -> None:
        """
        Cria o índice (idempotente) com mapeamento KNN baseado na dimensão do embedding.
        """
        if self.client.indices.exists(index=self.index):
            return

        body = {
            "settings": {
                "index": {
                    "number_of_shards": settings.OPENSEARCH_SHARDS,
                    "number_of_replicas": settings.OPENSEARCH_REPLICAS,
                    "knn": True,
                }
            },
            "mappings": {
                "properties": {
                    "text": {"type": "text"},
                    "metadata": {"type": "object", "enabled": True},
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": self.embedding_dim,
                        "method": {
                            "name": "hnsw",
                            "space_type": settings.KNN_SPACE,   # ex.: "l2" ou "cosinesimil"
                            "engine": settings.KNN_ENGINE,      # ex.: "faiss"
                        },
                    },
                }
            },
        }
        self.client.indices.create(index=self.index, body=body)

    def _ensure_index(self) -> None:
        self.ensure_index()

    def index_texts(self, texts: List[str]) -> Dict[str, Any]:
        """
        Indexa uma lista simples de textos (gera embeddings automaticamente).
        """
        docs = [{"text": t, "metadata": {}} for t in texts if (t or "").strip()]
        return self.index_docs(docs)

    def index_docs(self, docs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Indexa documentos no formato:
          {"text": str, "metadata": dict?, "id": str?}

        Usa bulk em lotes para melhor performance.
        """
        def _gen_actions() -> Iterable[Dict[str, Any]]:
            for d in docs:
                text = (d.get("text") or "").strip()
                if not text:
                    continue
                meta = d.get("metadata") or {}
                _id = d.get("id")

                emb = self.embedding_model.encode(text)
                emb_list = emb.tolist() if hasattr(emb, "tolist") else list(emb)

                action_meta = {"index": {"_index": self.index}}
                if _id:
                    action_meta["index"]["_id"] = _id
                yield action_meta
                yield {"text": text, "metadata": meta, "embedding": emb_list}

        chunk = 1000
        actions_iter = _gen_actions()
        total_indexed = 0

        while True:
            batch = list(islice(actions_iter, chunk * 2))
            if not batch:
                break
            res = self.client.bulk(body=batch, refresh=True)
            if res.get("errors"):
                pass
            total_indexed += sum(
                1
                for item in res.get("items", [])
                if "index" in item and int(item["index"].get("status", 500)) < 300
            )
        return {"ok": True, "indexed": total_indexed}

    def search_knn(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Executa uma busca KNN e retorna os hits brutos do OpenSearch.
        """
        emb = self.embedding_model.encode(query)
        vector = emb.tolist() if hasattr(emb, "tolist") else list(emb)

        body = {
            "size": top_k,
            "query": {
                "knn": {
                    "embedding": {
                        "vector": vector,
                        "k": top_k,
                    }
                }
            },
        }
        res = self.client.search(index=self.index, body=body)
        return res.get("hits", {}).get("hits", [])

    def _bm25_search(self, query: str, size: int = 10) -> List[Dict[str, Any]]:
        """
        Busca lexical (BM25) simples em 'text'.
        """
        body = {
            "size": size,
            "_source": True,
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["text"],
                    "type": "most_fields",
                }
            },
        }
        res = self.client.search(index=self.index, body=body)
        return res.get("hits", {}).get("hits", [])

    def search_knn_slim(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Versão “enxuta” dos resultados de KNN:
          [{"id": str, "score": float, "text": str, "meta": dict}, ...]
        """
        hits = self.search_knn(query, top_k=top_k)
        return [
            {
                "id": h.get("_id"),
                "score": h.get("_score"),
                "text": h.get("_source", {}).get("text", ""),
                "meta": h.get("_source", {}).get("metadata", {}),
            }
            for h in hits
        ]

    def search_hybrid_slim(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Fusão simples (RRF) entre KNN e BM25. Retorna no formato “slim”.
        """
        k = max(5, top_k)
        knn_hits = self.search_knn(query, top_k=k)
        bm25_hits = self._bm25_search(query, size=k)

        def to_rank_map(hits: List[Dict[str, Any]]) -> Dict[str, int]:
            m = {}
            for i, h in enumerate(hits, start=1):
                _id = h.get("_id")
                if _id:
                    m[_id] = i
            return m

        r_knn = to_rank_map(knn_hits)
        r_bm25 = to_rank_map(bm25_hits)

        K = 60.0
        ids = set(r_knn) | set(r_bm25)
        fused: List[Tuple[str, float]] = []
        for _id in ids:
            score = 0.0
            if _id in r_knn:
                score += 1.0 / (K + r_knn[_id])
            if _id in r_bm25:
                score += 1.0 / (K + r_bm25[_id])
            fused.append((_id, score))
        fused.sort(key=lambda x: x[1], reverse=True)

        src_by_id = {h.get("_id"): h.get("_source", {}) for h in (knn_hits + bm25_hits)}
        out = []
        for _id, score in fused[:top_k]:
            src = src_by_id.get(_id, {})
            out.append({
                "id": _id,
                "score": float(score),
                "text": src.get("text", ""),
                "meta": src.get("metadata", {}),
            })
        return out


def get_opensearch_service() -> OpenSearchService:
    return OpenSearchService()
