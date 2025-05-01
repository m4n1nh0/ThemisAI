from fastapi import APIRouter
from app.services.opensearch_service import search_service

router = APIRouter()


@router.post("/train")
def train(texts: list[str]):
    return search_service.index_texts(texts)
