from opensearchpy import OpenSearch
from sentence_transformers import SentenceTransformer
from app.config.settings import INDEX_NAME


class OpenSearchService:
    def __init__(self):
        self.client = OpenSearch(
            hosts=["http://localhost:9200"],
            http_auth=("admin", "admin")
        )
        self.embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
        self._create_index()  # Garante que o índice tem o mapeamento correto

    def _create_index(self):
        """Cria o índice com suporte para KNN se ele não existir"""
        if not self.client.indices.exists(index=INDEX_NAME):
            index_body = {
                "settings": {
                    "index": {
                        "knn": True
                    }
                },
                "mappings": {
                    "properties": {
                        "text": {"type": "text"},
                        "embedding": {
                            "type": "knn_vector",
                            "dimension": 384,  # Ajuste conforme o modelo usado
                            "method": {
                                "name": "hnsw",
                                "space_type": "l2",  # CORREÇÃO AQUI
                                "engine": "faiss"
                            }
                        }
                    }
                }
            }
            self.client.indices.create(index=INDEX_NAME, body=index_body)
            print(f"Índice '{INDEX_NAME}' criado com sucesso!")

    def index_texts(self, texts: list[str]):
        """Armazena os textos e seus embeddings no OpenSearch"""
        for text in texts:
            embedding = self.embedding_model.encode(text).tolist()
            self.client.index(index=INDEX_NAME, body={"text": text, "embedding": embedding})
        return {"message": "Texts indexed successfully"}

    def search_best_match(self, query: str):
        """Busca o texto mais próximo com base no embedding"""
        embedding = self.embedding_model.encode(query).tolist()
        search_result = self.client.search(index=INDEX_NAME, body={
            "size": 1,
            "query": {
                "knn": {
                    "embedding": {
                        "vector": embedding,
                        "k": 1
                    }
                }
            }
        })

        hits = search_result.get("hits", {}).get("hits", [])
        if hits:
            return hits[0]["_source"]["text"]
        return "Nenhuma resposta encontrada no banco de conhecimento."


search_service = OpenSearchService()
