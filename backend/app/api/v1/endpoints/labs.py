from datetime import UTC, datetime

from fastapi import APIRouter

from app.schemas.v1.labs import (
    FoodGuidance,
    LabsInterpretRequest,
    LabsInterpretSuccess,
    MarkerResult,
    NutrientTheme,
    Source,
    SupportStatus,
)

router = APIRouter()


@router.post("/interpret", response_model=LabsInterpretSuccess)
async def interpret_lab(payload: LabsInterpretRequest) -> LabsInterpretSuccess:
    comparison = "unknown"
    if payload.reference_range.low is not None and payload.value < payload.reference_range.low:
        comparison = "below_range"
    elif payload.reference_range.high is not None and payload.value > payload.reference_range.high:
        comparison = "above_range"
    elif payload.reference_range.low is not None or payload.reference_range.high is not None:
        comparison = "within_range"

    return LabsInterpretSuccess(
        interpretation_id="lab_interp_stub_001",
        supported_marker=True,
        marker=MarkerResult(
            name=payload.marker_name,
            normalized_name=payload.marker_name,
            value=payload.value,
            unit=payload.unit,
        ),
        range_comparison=comparison,
        used_user_range=True,
        nutrient_themes=[
            NutrientTheme(
                theme="general_balanced_diet",
                reason="Mock guidance stays food-based and non-clinical.",
            )
        ],
        food_guidance=[
            FoodGuidance(
                guidance_type="general_note",
                message="Use this mock result as general food guidance only.",
                foods=["beans", "leafy greens", "whole grains"],
            )
        ],
        safety_flags=[
            "non_diagnostic",
            "no_treatment_advice",
            "no_supplement_prescription",
        ],
        support_status=SupportStatus(
            status="supported",
            reason="Mock marker accepted with the user-provided reference range.",
        ),
        source=Source(
            provider="validated_lab_marker_mapping_table",
            source_type="lab_marker_rules",
            fetched_at=datetime.now(UTC),
        ),
        warnings=["Mock response. Consult a clinician for medical interpretation."],
    )
