from fastapi import APIRouter

from app.api.v1.endpoints import barcode, chat, labs, nutrition, plans


api_router = APIRouter(prefix="/v1")

api_router.include_router(barcode.router)
api_router.include_router(chat.router)
api_router.include_router(labs.router)
api_router.include_router(nutrition.router)
api_router.include_router(plans.router)