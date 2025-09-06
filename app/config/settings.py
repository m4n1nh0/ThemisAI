from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Configurações da aplicação carregadas via variáveis de ambiente (.env).

    - 'APP_NAME': Nome do serviço
    - 'DEBUG': Ativa modo de desenvolvimento (reload, logs verbosos)
    - 'SECRET_KEY': Chave secreta para assinar JWT
    - 'ALGORITHM': Algoritmo de assinatura JWT (ex.: HS256)
    - 'ACCESS_TOKEN_EXPIRE_MINUTES': Minutos até expiração do token

    - 'LLAMA_CPP_PATH': Caminho para o binário do llama.cpp
    - 'MODEL_PATH': Caminho do modelo GGUF (ex.: .gguf)

    - 'INDEX_NAME': Nome do índice padrão no OpenSearch

    - 'OPENSEARCH_HOST': URL do OpenSearch (ex.: http://opensearch:9200)
    - 'OPENSEARCH_USER': Usuário do OpenSearch (se aplicável)
    - 'OPENSEARCH_PASS': Senha do OpenSearch (se aplicável)
    - 'OPENSEARCH_TIMEOUT': Timeout de requests ao OpenSearch (s)
    - 'OPENSEARCH_SHARDS': Nº de shards do índice
    - 'OPENSEARCH_REPLICAS': Nº de réplicas do índice

    - 'EMBED_MODEL_NAME': Nome do modelo de embeddings do Sentence-Transformers
    - 'KNN_ENGINE': Engine KNN no OpenSearch (faiss|nmslib|lucene)
    - 'KNN_SPACE': Espaço de similaridade (l2|cosine|innerproduct)
    """
    APP_NAME: str = "fastapi-llama-api"
    DEBUG: bool = True

    SECRET_KEY: str = Field(..., min_length=16)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    LLAMA_CPP_PATH: str = "/app/llama.cpp/build/bin/llama-bin"
    MODEL_PATH: str = "/models/mistral-7b-instruct-v0.1.Q4_K_M.gguf"

    INDEX_NAME: str = "knowledge_base"
    OPENSEARCH_HOST: str = "http://opensearch:9200"
    OPENSEARCH_USER: str | None = "admin"
    OPENSEARCH_PASS: str | None = "admin"
    OPENSEARCH_TIMEOUT: int = 15
    OPENSEARCH_SHARDS: int = 1
    OPENSEARCH_REPLICAS: int = 0

    EMBED_MODEL_NAME: str = "sentence-transformers/all-MiniLM-L6-v2"
    KNN_ENGINE: str = "faiss"
    KNN_SPACE: str = "l2"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
