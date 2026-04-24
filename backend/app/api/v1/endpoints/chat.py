from fastapi import APIRouter, HTTPException, status

from app.schemas.v1.chat import ChatQueryRequest, ChatQueryResponse
from app.services.chat_service import ChatService
from app.services.exceptions import NotFoundError, UpstreamUnavailableError


router = APIRouter(prefix="/chat", tags=["chat"])


@router.post(
    "/query",
    response_model=ChatQueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Answer a grounded nutrition or product question",
)
async def query_chat(payload: ChatQueryRequest) -> ChatQueryResponse:
    """
    POST /v1/chat/query

    Answers a user question using backend-approved context, source references,
    and safety flags.
    """
    try:
        return await ChatService.query(payload)

    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except UpstreamUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected chat query failure.",
        ) from exc