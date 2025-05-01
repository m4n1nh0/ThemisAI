from fastapi import APIRouter
from app.services.opensearch_service import search_service
from app.services.llama_service import llama_service

router = APIRouter()


@router.post("/ask")
def ask(question: str):
    best_match = search_service.search_best_match(question)
    response = llama_service.generate_response(best_match)
    return {"answer": response}
