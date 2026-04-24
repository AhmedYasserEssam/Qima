from fastapi import FastAPI

from app.api.v1.router import api_router
from app.api.v1.endpoints.health import router as health_router

app = FastAPI(title="Qima API", version="1.0.0")

app.include_router(health_router, tags=["health"])
app.include_router(api_router)
