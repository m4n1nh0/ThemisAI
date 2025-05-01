from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import timedelta
from app.db.database import auth_service

router = APIRouter()


class UserCreate(BaseModel):
    username: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


@router.post("/register")
def register(user: UserCreate):
    return auth_service.register_user(user.username, user.password)


@router.post("/login")
def login(user: UserLogin):
    db_user = auth_service.authenticate_user(user.username, user.password)
    if not db_user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = auth_service.create_access_token(
        {"sub": user.username}, timedelta(minutes=30)
    )
    return {"access_token": access_token, "token_type": "bearer"}
