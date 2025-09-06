"""
Serviço de integração com OpenSearch para RAG.

Recursos:
- Cliente com timeouts e retries.
- Criação idempotente de índice com KNN (FAISS/HNSW).
- Indexação em lote (bulk) para performance.
- Busca KNN (hits brutos) e "slim" (id, score, text, meta).
- Dimensão do embedding inferida do modelo Sentence-Transformers.

Compatível com docker-compose:
  OPENSEARCH_HOST=http://opensearch:9200
"""

from __future__ import annotations
from typing import List, Dict, Any, Iterable, Optional
from itertools import islice

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

        http_auth = HTTPBasicAuth(user, password) if user and password else None
        self.client = OpenSearch(
            hosts=[host],
            http_auth=http_auth,
            use_ssl=str(host).startswith("https"),
            verify_certs=False,
            connection_class=RequestsHttpConnection,
            timeout=timeout,
            max_retries=3,
            retry_on_timeout=True,
        )

        self.embedding_model = SentenceTransformer(embed_model_name)
        self.embedding_dim = int(self.embedding_model.get_sentence_embedding_dimension())

        # ---- Garante índice ----
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
                            "space_type": settings.KNN_SPACE,
                            "engine": settings.KNN_ENGINE,
                        },
                    },
                }
            },
        }
        self.client.indices.create(index=self.index, body=body)

    def _ensure_index(self) -> None:
        """Alias para ensure_index()."""
        self.ensure_index()

    def index_texts(self, texts: List[str]) -> Dict[str, Any]:
        """
        Indexa uma lista simples de textos (gera embeddings automaticamente).

        - `texts`: lista de strings
        - return: {"ok": True, "indexed": <qtd>}
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


def get_opensearch_service() -> OpenSearchService:
    return OpenSearchService()
