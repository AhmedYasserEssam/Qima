from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps.auth import get_current_user
from app.models.user import User
from app.schemas.v1.error import ErrorResponse
from app.schemas.v1.inventory import (
    InventoryBarcodeAddRequest,
    InventoryDeleteResponse,
    InventoryImageAddRequest,
    InventoryItemsResponse,
    InventoryManualAddRequest,
)
from app.services.exceptions import BadRequestError, NotFoundError, UpstreamUnavailableError
from app.services.inventory_service import inventory_service

router = APIRouter()


@router.get(
    "/items",
    response_model=InventoryItemsResponse,
)
async def list_inventory_items(
    current_user: User = Depends(get_current_user),
) -> InventoryItemsResponse:
    return inventory_service.list_items(user=current_user)


@router.post(
    "/items/manual",
    response_model=InventoryItemsResponse,
    responses={400: {"model": ErrorResponse}},
)
async def add_manual_inventory_items(
    payload: InventoryManualAddRequest,
    current_user: User = Depends(get_current_user),
) -> InventoryItemsResponse:
    try:
        return inventory_service.add_manual_items(
            user=current_user,
            item_names=payload.items,
        )
    except BadRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/items/from-image",
    response_model=InventoryItemsResponse,
    responses={400: {"model": ErrorResponse}},
)
async def add_inventory_items_from_image(
    payload: InventoryImageAddRequest,
    current_user: User = Depends(get_current_user),
) -> InventoryItemsResponse:
    try:
        return inventory_service.add_image_selected_items(
            user=current_user,
            image_id=payload.image_id,
            recognized_ingredients=payload.recognized_ingredients,
            selected_ingredients=payload.selected_ingredients,
        )
    except BadRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/items/from-barcode",
    response_model=InventoryItemsResponse,
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def add_inventory_item_from_barcode(
    payload: InventoryBarcodeAddRequest,
    current_user: User = Depends(get_current_user),
) -> InventoryItemsResponse:
    try:
        return await inventory_service.add_item_from_barcode(
            user=current_user,
            barcode=payload.barcode,
        )
    except BadRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UpstreamUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.delete(
    "/items/{item_id}",
    response_model=InventoryDeleteResponse,
    responses={404: {"model": ErrorResponse}},
)
async def delete_inventory_item(
    item_id: int,
    current_user: User = Depends(get_current_user),
) -> InventoryDeleteResponse:
    try:
        return inventory_service.delete_item(user=current_user, item_id=item_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
