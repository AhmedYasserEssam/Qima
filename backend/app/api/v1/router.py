from fastapi import APIRouter

from app.api.v1.endpoints import (
    barcode,
    chat,
    health,
    labs,
    nutrition,
    plans,
    prices,
    profile,
    recipes,
    vision,
)

api_router = APIRouter(prefix="/v1")

api_router.include_router(health.router, tags=["health"])
api_router.include_router(barcode.router, prefix="/barcode", tags=["barcode"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(labs.router, prefix="/labs", tags=["labs"])
api_router.include_router(nutrition.router, prefix="/nutrition", tags=["nutrition"])
api_router.include_router(plans.router, prefix="/plans", tags=["plans"])
api_router.include_router(prices.router, prefix="/prices", tags=["prices"])
api_router.include_router(profile.router, prefix="/profile", tags=["profile"])
api_router.include_router(recipes.router, prefix="/recipes", tags=["recipes"])
api_router.include_router(vision.router, prefix="/vision", tags=["vision"])