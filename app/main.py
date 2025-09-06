from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from app.routes import auth, training as train, ask


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from app.services.opensearch_service import OpenSearchService
        osvc = OpenSearchService()
        try:
            osvc._ensure_index()
        except Exception:
            pass
    except Exception:
        pass
    yield


app = FastAPI(
    title="FastAPI LLaMA API",
    version="0.1.0",
    description="API para RAG com OpenSearch + LLaMA",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

# CORS (restrinja em PROD)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Healthcheck simples
@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


# Rotas
app.include_router(auth.router)
app.include_router(train.router)
app.include_router(ask.router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
