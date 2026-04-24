from fastapi import APIRouter, File, Form, UploadFile

from app.schemas.v1.vision import (
    DishCandidate,
    IngredientCandidate,
    VisionDataQuality,
    VisionIdentifyRequestMetadata,
    VisionIdentifyResponse,
    VisionSource,
)

router = APIRouter()


@router.post("/identify", response_model=VisionIdentifyResponse)
async def identify_food_image(
    image: UploadFile = File(...),
    locale: str | None = Form(default=None),
) -> VisionIdentifyResponse:
    metadata = VisionIdentifyRequestMetadata(locale=locale)

    return VisionIdentifyResponse(
        image_id="img_stub_001",
        dish_candidates=[
            DishCandidate(name="koshari", confidence=0.82),
        ],
        ingredients=[
            IngredientCandidate(name="rice", confidence=0.78),
            IngredientCandidate(name="lentils", confidence=0.74),
        ],
        confidence=0.8,
        source=VisionSource(
            provider="google_gemini",
            model="gemini-2.5-flash",
            source_type="vision_model",
        ),
        data_quality=VisionDataQuality(completeness="partial"),
        warnings=[
            f"Stub response for uploaded file: {image.filename}",
            f"Locale received: {metadata.locale}",
        ],
        latency_ms=180,
    )