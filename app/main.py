from fastapi import FastAPI
from app.routes import auth, train, ask

app = FastAPI()

app.include_router(auth.router)
app.include_router(train.router)
app.include_router(ask.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
