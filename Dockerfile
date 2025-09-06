# Stage 1: builder
FROM python:3.10-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# deps de build (removidas no runtime)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git pkg-config curl libopenblas-dev \
    && rm -rf /var/lib/apt/lists/*

# instalar deps python (gera wheels se necessário)
COPY requirements.txt .
RUN pip install --upgrade pip && pip wheel -r requirements.txt -w /build/wheels

# copiar código
COPY app ./app
COPY scripts ./scripts
COPY models ./models
COPY llama.cpp ./llama.cpp

# se a pasta não estiver no contexto, clone do Git
RUN if [ ! -f /build/llama.cpp/CMakeLists.txt ]; then \
      echo "[llama] source não veio no contexto; clonando..."; \
      git clone --depth 1 https://github.com/ggerganov/llama.cpp.git /build/llama.cpp; \
    fi

# === Compila llama.cpp (e cria alias estável) ===
RUN set -eux; \
    rm -rf /build/llama.cpp/build; \
    cmake -S /build/llama.cpp -B /build/llama.cpp/build \
      -DCMAKE_BUILD_TYPE=Release \
      -DGGML_BLAS=ON -DGGML_OPENMP=ON -DBLAS=OpenBLAS; \
    cmake --build /build/llama.cpp/build --config Release -j "$(nproc)"; \
    BIN="/build/llama.cpp/build/bin"; \
    if   [ -x "$BIN/llama-cli"    ]; then TGT="$BIN/llama-cli"; \
    elif [ -x "$BIN/llama-bin"    ]; then TGT="$BIN/llama-bin"; \
    elif [ -x "$BIN/llama-simple" ]; then TGT="$BIN/llama-simple"; \
    elif [ -x "$BIN/main"         ]; then TGT="$BIN/main"; \
    elif [ -x "$BIN/llama"        ]; then TGT="$BIN/llama"; \
    else CAND="$(sh -lc "ls -1 $BIN/llama-* 2>/dev/null | head -n1" || true)"; \
         if [ -n "$CAND" ] && [ -x "$CAND" ]; then TGT="$CAND"; \
         else echo "Nenhum binário do llama.cpp encontrado em $BIN"; ls -la "$BIN" || true; exit 1; fi; \
    fi; \
    ln -sf "$TGT" "$BIN/llama-bin"; \
    "$BIN/llama-bin" -h || true


# Stage 2: runtime
FROM python:3.10-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TOKENIZERS_PARALLELISM=false

WORKDIR /app

# libs de runtime (sem toolchain de build)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libopenblas0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# instalar deps python a partir dos wheels gerados no builder
COPY --from=builder /build/wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/*

# copiar app, scripts e TODO o build do llama.cpp (inclui libllama.so)
COPY --from=builder /build/app /app/app
COPY --from=builder /build/scripts /app/scripts
COPY --from=builder /build/models ./models
COPY --from=builder /build/llama.cpp/build /app/llama.cpp/build

# usuário não-root
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# paths e binário
ENV LD_LIBRARY_PATH=/app/llama.cpp/build:/app/llama.cpp/build/lib:/app/llama.cpp/build/bin:$LD_LIBRARY_PATH \
    LLAMA_CPP_PATH=/app/llama.cpp/build/bin/llama-cli \
    APP_MODULE=app.main:app \
    HOST=0.0.0.0 \
    PORT=8000 \
    RELOAD=false

CMD ["sh", "-c", "uvicorn ${APP_MODULE} --host ${HOST} --port ${PORT} $( [ \"$RELOAD\" = \"true\" ] && echo --reload )"]
