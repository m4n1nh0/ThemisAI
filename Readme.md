# FastAPI LLaMA RAG API

API em **FastAPI** para **RAG (Retrieval-Augmented Generation)** usando **OpenSearch** para recuperação de contexto e **LLaMA** (via `llama.cpp`) para geração.
Inclui autenticação com **Bearer Token (PyJWT)**, ingestão com **chunking**, e **Docker** com build do `llama.cpp` dentro da imagem.

## Visão Geral

* **RAG**: busca no OpenSearch (KNN + embeddings `sentence-transformers`) → monta prompt → gera resposta no LLaMA.
* **Auth**: login/registro + JWT com `HTTPBearer`.
* **Prod-ready basics**: indexação em *bulk*, retries/timeouts, CORS, `/health`, `.env`.
* **Docker**: `llama.cpp` é **compilado** no build; modelos são montados via volume.

---

## Arquitetura

```
app/
  config/
    settings.py          # Configurações via .env (Pydantic)
    security.py          # get_current_user (HTTPBearer + PyJWT)
  db/
    dto/
      user_dto.py        # DTO de usuários
    sqlite.py            # Conexão + schema (SQLite para DEV/PoC)
  services/
    opensearch_service.py# OpenSearch + embeddings + KNN + bulk
    llama_service.py     # Adapter para binário do llama.cpp (async)
  domain/
    auth_domain.py       # Hash + JWT + autenticação
    rag_domain.py        # Regras de negócio do RAG (prompt/orquestração)
  routes/
    auth.py              # /auth/register, /auth/login
    training.py          # /training/train  (ingestão com chunking)
    ask.py               # /ask/question    (RAG)
  main.py                # App, CORS, /health, lifespan opcional
```

---

## Stack

* **FastAPI**, **Uvicorn**, **orjson**
* **OpenSearch** (`opensearch-py`) com **KNN (FAISS/HNSW)**
* **Sentence-Transformers** (`all-MiniLM-L6-v2` por padrão)
* **PyJWT**, **passlib\[bcrypt]**
* **llama.cpp** (compilado no Docker)

---

## Pré-requisitos

* Docker + Docker Compose
* Modelo `.gguf` (ex.: `mistral-7b-instruct-v0.1.Q4_K_M.gguf`) em `./models` (montado no container)

---

## Início Rápido (Docker)

1. Crie o arquivo `.env` a partir do exemplo:

   ```bash
   cp .env.example .env
   ```

   Ajuste pelo menos:

   ```
   SECRET_KEY=<coloque-uma-chave-forte>
   MODEL_PATH=/models/mistral-7b-instruct-v0.1.Q4_K_M.gguf
   ```

2. Suba a stack:

   ```bash
   docker compose up --build
   ```

3. Verifique:

   * API: [http://localhost:8000/health](http://localhost:8000/health)
   * Docs: [http://localhost:8000/docs](http://localhost:8000/docs)

> O `Dockerfile` compila o `llama.cpp` (CPU + OpenBLAS) e deixa o binário em `/app/llama.cpp/build/bin/llama-simple`.
> O caminho padrão do binário é definido por `LLAMA_CPP_PATH` no `.env`.

---

## Variáveis de Ambiente (chaves principais)

Veja `.env.example` completo; principais:

```
APP_NAME=fastapi-llama-api
DEBUG=true

# Auth
SECRET_KEY=troque-esta-chave-super-secreta
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# OpenSearch
OPENSEARCH_HOST=http://opensearch:9200
OPENSEARCH_USER=admin
OPENSEARCH_PASS=admin
INDEX_NAME=knowledge_base
OPENSEARCH_SHARDS=1
OPENSEARCH_REPLICAS=0
OPENSEARCH_TIMEOUT=15

# Embeddings / KNN
EMBED_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2
KNN_ENGINE=faiss
KNN_SPACE=l2

# LLaMA
LLAMA_CPP_PATH=/app/llama.cpp/build/bin/llama-simple
MODEL_PATH=/models/mistral-7b-instruct-v0.1.Q4_K_M.gguf
```

---

## Endpoints

### Health

* `GET /health` → `{"status":"ok"}`

### Auth

* `POST /auth/register`

  ```json
  { "username": "alice", "password": "secret123" }
  ```
* `POST /auth/login` → `{ "access_token": "...", "token_type": "bearer" }`

### Training (protegido: Bearer)

* `POST /training/train`
  **Modo simples**:

  ```json
  { "texts": ["texto 1", "texto 2"] }
  ```

  **Modo avançado (docs + metadata + chunking)**:

  ```json
  {
    "docs": [
      { "id": "doc1", "text": "conteúdo longo...", "metadata": {"source":"manual"} }
    ],
    "chunk_size": 800,
    "chunk_overlap": 100
  }
  ```

### Ask (protegido: Bearer)

* `POST /ask/question`

  ```json
  {
    "question": "Qual é o índice padrão?",
    "top_k": 3,
    "max_tokens": 200
  }
  ```

  **Resposta:**

  ```json
  {
    "answer": "...",
    "citations": [
      {"id":"...","score":12.3,"text":"...","meta":{"source":"..."}}
    ]
  }
  ```

---

## Autenticação: Bearer Token

1. Registre:

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"secret123"}'
```

2. Faça login e capture o token:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"secret123"}' | jq -r .access_token)
```

3. Use o token:

```bash
curl -X POST http://localhost:8000/training/train \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"texts":["A API usa FastAPI e integra LLaMA e OpenSearch."]}'

curl -X POST http://localhost:8000/ask/question \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"Qual índice padrão?","top_k":3,"max_tokens":128}'
```

---

## Fluxo RAG (Domínio)

1. `OpenSearchService.search_knn_slim()` recupera `top_k` trechos (KNN).
2. `RagDomain.build_prompt()` monta o prompt com os trechos + instrução do sistema.
3. `LlamaService.generate_response_async()` chama o `llama.cpp` e retorna a resposta.
4. A API responde com **answer + citations**.

---

## Desenvolvimento local (sem Docker)

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt

# Suba OpenSearch separadamente (ou via Docker) e configure OPENSEARCH_HOST
uvicorn app.main:app --reload
```

> Para CPU/Windows, se `torch` não tiver wheel compatível, instale via:
>
> ```
> pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
> ```

---

## Testes e Qualidade

```bash
pytest --cov=app --cov-report=term-missing
ruff check .
black --check .
```

---

## Popular Dados (Como usar)

### Pegar token:

```
$TOKEN = (curl.exe -s -X POST http://localhost:8000/auth/login `
  -H "Content-Type: application/json" `
  -d "{\"username\":\"admin\",\"password\":\"secret123\"}" | ConvertFrom-Json).access_token

```


### Ingestar técnicas + mitigações + relações (com limite pra testar):

```
python .\scripts\ingest_mitre_mobile.py `
  --api http://localhost:8000 `
  --token $TOKEN `
  --include techniques,mitigations,relations `
  --limit 200 `
  --chunk-size 800 `
  --chunk-overlap 100
```

### Ingestar apenas mitigações:

```
python .\scripts\ingest_mitre_mobile.py `
  --api http://localhost:8000 `
  --token $TOKEN `
  --include mitigations
```

----

## Troubleshooting

* **`/health` ok mas `/ask` falha**: verifique `MODEL_PATH` (arquivo `.gguf` montado em `/models`) e `LLAMA_CPP_PATH`.
* **OpenSearch não pronto**: o `compose` já usa `depends_on: service_healthy`, mas aguarde o `opensearch` ficar verde.
* **Erro de wheel do `torch`**: instale via índice CPU do PyTorch (ver “Desenvolvimento local”).
* **Mudou `EMBED_MODEL_NAME` / `KNN_*`**: crie outro índice (`INDEX_NAME`) ou drope/recrie o existente.

---

## Licença

MIT — veja `LICENSE` (se ainda não houver, crie um arquivo `LICENSE` com MIT).

---

## Roadmap curto

* Rate limit por usuário/IP
* Métricas Prometheus
* Re-ranking opcional (BM25 → LLM/TEI)
* Integração com vLLM / OpenAI-compat (adapter)
* CI com lint + testes no PR
