# ThemisAI – FastAPI LLaMA RAG para Segurança Mobile (MITRE ATT\&CK)

A **ThemisAI** é uma API em **FastAPI** que implementa **RAG (Retrieval-Augmented Generation)** para responder perguntas sobre **Segurança Mobile** (Android/iOS), usando:

* **OpenSearch** para **recuperar conhecimento** (técnicas, mitigações, detecções e relações) do **MITRE ATT\&CK for Mobile**;
* **LLaMA (llama.cpp)** para **gerar respostas** claras, rastreáveis e **baseadas no contexto** retornado pelo repositório MITRE.

> **O que ela é:** uma IA de apoio a decisões e consultas técnicas sobre defesa, detecção, TTPs e mitigação em mobile, **alimentada por conteúdo oficial do MITRE ATT\&CK for Mobile** (via STIX), com **citações** das fontes recuperadas.
> **O que ela não é:** não é um produto oficial da MITRE, nem substitui análise humana. Serve como **copiloto** para times de Sec/Eng/DFIR, elevando a velocidade e a padronização de respostas.

---

## Como funciona (em linguagem simples)

1. **Ingestão** (scripts/ingest\_mitre\_mobile.py)
   Baixa a coleção **Mobile ATT\&CK** (STIX 2.1) do GitHub oficial da MITRE, extrai **técnicas (attack-pattern)**, **mitigações (course-of-action)**, **relações** (quem usa o quê) e campos úteis (**táticas, plataformas, detecções, referências**).
   Em seguida:

   * **“achata”** (normaliza) o conteúdo em **documentos** legíveis, com **metadados** (ex.: `attack_id`, `urls`, `source`).
   * **fatia** textos longos em *chunks* (com overlap) preservando metadados, e **indexa** no OpenSearch com **embeddings**.

2. **Recuperação (R)**
   Na pergunta do usuário (ex.: *“O que a MITRE fala sobre permissionamento mobile?”*), o serviço consulta o OpenSearch com **KNN** (e, opcionalmente, **busca híbrida** BM25+KNN com RRF), retornando os **trechos mais relevantes** já com escore e fonte (URL).

3. **Geração (G)**
   Montamos um **prompt** que inclui a pergunta + os trechos. O **LLaMA** responde **apenas com base no contexto**, e você pode escolher **presets de estilo** (ex.: *audit-bullets*, *qa*, *mitre-card*, *json*, etc.) para formatos de saída padronizados.

4. **Resposta auditável**
   A API retorna `answer` + `citations`. Como os **metadados** são mantidos, fica fácil **trilhar as fontes** na MITRE (links `attack.mitre.org`).

---

## Por que isso é útil em Segurança Mobile?

* **Padroniza** respostas com base em MITRE (evita divergências de referência).
* **Acelera** investigações (DFIR, Red/Blue Team) com **resumos**, **cartões MITRE**, **bullets auditáveis**.
* **Ajuda em comunicação executiva** via presets como `exec-summary`.
* **Cobre Android e iOS**, incluindo **plataformas**, **táticas** e **detecções** (`x_mitre_detection` quando disponível).

**Exemplos de perguntas úteis:**

* “Quais **mitigações** a MITRE recomenda para a técnica T14xx?”
* “Como **detectar** exploração via interfaces de rádio?”
* “Quais **grupos ou malwares** usam a técnica X?”
* “Compare **mitigações** relevantes para *juice jacking*.”
* “Faça um **resumo executivo** sobre riscos desta técnica em iOS.”

---

## Arquitetura (visão técnica)

```
Cliente → /ask/question ─┐
                         │   [R] Retriever (OpenSearchService)
                         ├─► busca KNN/híbrida + metadados (URLs, táticas, plataformas…)
                         │
                         │   [A] Aggregator (RagDomain)
                         ├─► filtra/dedup/empacota contexto por orçamento de tokens
                         │   monta prompt (estilos opcionais)
                         │
                         │   [G] Generator (LlamaService)
                         └─► chama llama.cpp (modelo .gguf) com limite de tokens só da resposta
                              ↓
                       answer + citations (com Fonte)
```

* **OpenSearch**: índice KNN com **embeddings** `sentence-transformers` (`all-MiniLM-L6-v2` por padrão).
* **RagDomain**: políticas (dedupe, mínimo de citações, budget de contexto), prompts por **preset**.
* **LlamaService**: autodetecção do binário (`llama-cli`, `llama-simple`, etc.), **assíncrono**, *fallback* de flags.
* **Auth**: **Bearer JWT** (PyJWT + HTTPBearer) para /training e /ask.

---

## Estilos de resposta (presets)

Use o campo `style` em `/ask/question`:

* **base** *(padrão)* – resposta detalhada com trechos.
* **audit-bullets** – bullets curtos e verificáveis, com `[n]` simulando referências.
* **concise** – 3–6 bullets concisos com `[n]`.
* **qa** – resposta direta + detalhes em bullets `[n]`.
* **compare** – **tabela** “Item | Evidência \[n] | Observações”.
* **table** – **tabela** “Campo | Conteúdo | Fonte \[n]”.
* **json** – **apenas JSON** (`answer`, `bullets[]`, `citations_used[]`).
* **mitre-card** – cartão MITRE (Tática/Técnica/Plataformas/Mitig./Detec./Refs).

> **Dica de performance:** `answer_max_tokens` controla **somente o tamanho da resposta** do modelo (não o contexto).
> Em mobile, 400–1000 costuma ser ótimo para respostas auditáveis.

---

## Endpoints principais

### Health

* `GET /health` → `{"status":"ok"}`

### Auth

* `POST /auth/register`
  `{"username":"alice","password":"secret123"}`
* `POST /auth/login` → `{ "access_token": "...", "token_type": "bearer" }`

### Training (protegido)

* `POST /training/train`

  * **Simples**:

    ```json
    { "texts": ["texto 1", "texto 2"] }
    ```
  * **Avançado** (mantém **metadados**; **chunking** configurável):

    ```json
    {
      "docs": [
        {
          "id": "T1477",
          "text": "conteúdo longo…",
          "metadata": {
            "source": "MITRE ATT&CK Mobile",
            "attack_id": "T1477",
            "urls": ["https://attack.mitre.org/techniques/T1477/"]
          }
        }
      ],
      "chunk_size": 800,
      "chunk_overlap": 100
    }
    ```

### Ask (protegido)

* `POST /ask/question`

  ```json
  {
    "question": "O que a MITRE recomenda para permissionamento mobile?",
    "top_k": 8,
    "answer_max_tokens": 600,
    "style": "audit-bullets"
  }
  ```

  **Resposta:**

  ```json
  {
    "answer": "…",
    "citations": [
      {"id":"T1477","score":12.3,"text":"…","meta":{"url":"https://attack.mitre.org/techniques/T1477/"}}
    ]
    }
  ```

---

## Início rápido (Docker)

1. Crie o `.env`:

```bash
cp .env.example .env
```

Edite:

```
SECRET_KEY=<chave-forte>
MODEL_PATH=/models/mistral-7b-instruct-v0.1.Q4_K_M.gguf
```

2. Suba:

```bash
docker compose up --build 
```
```bash
docker compose up 
```

Copie:

```
docker cp models/mistral-7b-instruct-v0.1.Q4_K_M.gguf themis-ai-api:/models/
```

3. Teste o LLaMA dentro do container:

```bash
docker compose exec themis-ai python /app/scripts/smoke_llama.py --prompt "oi" --max-tokens 16 --timeout 300
```

4. Faça login e capture token (PowerShell):

```powershell
$TOKEN = (curl.exe -s -X POST http://localhost:8000/auth/login `
  -H "Content-Type: application/json" `
  -d "{\"username\":\"admin\",\"password\":\"secret123\"}" | ConvertFrom-Json).access_token
```

5. Ingeste MITRE Mobile (técnicas/mitigações/relações):

```powershell
python .\scripts\ingest_mitre_mobile.py `
  --api http://localhost:8000 `
  --token $TOKEN `
  --include techniques,mitigations,relations `
  --limit 200 `
  --chunk-size 800 `
  --chunk-overlap 100
```

---

## Variáveis de ambiente (principais)

```
APP_NAME=fastapi-llama-api
DEBUG=true

# Auth
SECRET_KEY=troque-esta-chave
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# OpenSearch
OPENSEARCH_HOST=http://opensearch-node1:9200
OPENSEARCH_USER=
OPENSEARCH_PASS=
INDEX_NAME=knowledge_base
OPENSEARCH_SHARDS=1
OPENSEARCH_REPLICAS=0
OPENSEARCH_TIMEOUT=15

# Embeddings / KNN
EMBED_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2
KNN_ENGINE=faiss
KNN_SPACE=l2

# LLaMA
LLAMA_CPP_PATH=/app/llama.cpp/build/bin/llama-cli
MODEL_PATH=/models/mistral-7b-instruct-v0.1.Q4_K_M.gguf
```

---

## Boas práticas de perguntas (Mobile)

* **Seja específico**: cite técnica (`T14xx`), plataforma (*Android/iOS*), fase (tática) ou cenário (ex.: *“USB charging station / juice jacking”*).
* **Peça formato útil**: `style: "mitre-card"` para visão 360º, `compare` para decidir entre mitigações, `exec-summary` para liderança.
* **Use “detecções”** quando quiser pistas de **telemetria**/indicadores (`x_mitre_detection`).

---

## Operação & Performance

* **Primeiro load do modelo** pode levar 1–3 min; depois acelera.
* **`answer_max_tokens`** alto = resposta longa + **mais lenta**. Prefira 400–1000 para auditoria.
* **Híbrida (BM25+KNN)** pode ajudar em perguntas muito **lexicais**; ative conforme sua relevância.
* **Recrie o índice** se trocar `EMBED_MODEL_NAME`/mapeamento (ou use `INDEX_NAME` novo).

---

## Limitações e ética

* **Cobertura** depende do **bundle MITRE** ingerido.
* **Não inventar**: os prompts forçam “não encontrado no contexto” quando faltar base.
* **Use como apoio**, não como fonte exclusiva. Valide decisões críticas com especialistas.

---

## Desenvolvimento local (sem Docker)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload
```

> Em CPU/Windows, se `torch` não vier:
> `pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu`

---

## Troubleshooting

* **Binário não encontrado**: ajuste `LLAMA_CPP_PATH` ou deixe a autodetecção encontrar `llama-cli`/`llama-simple`.
* **Timeout na 1ª resposta**: aumente `--timeout` no `smoke_llama.py` (carregamento inicial).
* **Erro de wheel do torch**: instale via índice CPU do PyTorch (ver “Desenvolvimento local”).
* **OpenSearch security duplicada**: evite definir `plugins.security.disabled` e `DISABLE_SECURITY_PLUGIN` ao mesmo tempo.

---

## Licença

Este projeto segue a licença MIT.

---

## Roadmap

* Métricas (Prometheus), rate limit, CI/CD.
* Re-ranker opcional (BM25 → re-ranker → LLM).
* Adapter OpenAI-compat / vLLM.
* Dashboards prontos (Detec/ Mitig por plataforma/tática).
