from __future__ import annotations

import importlib.abc
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.exceptions import UpstreamUnavailableError


@dataclass(frozen=True)
class ImageOcrResult:
    text: str
    images_processed: int


class ImageOcrService:
    def __init__(self, *, ocr: Any | None = None) -> None:
        self._ocr = ocr

    def extract_text_from_images(self, image_paths: list[Path]) -> ImageOcrResult:
        ocr = self._get_ocr()
        chunks: list[str] = []
        for image_path in image_paths:
            try:
                result = ocr.ocr(str(image_path))
            except (OSError, RuntimeError) as exc:
                raise UpstreamUnavailableError(
                    f"PaddleOCR could not process image '{image_path.name}': {exc}."
                ) from exc
            chunks.extend(_extract_text_lines(result))
        return ImageOcrResult(
            text="\n".join(chunks).strip(), images_processed=len(image_paths)
        )

    def _get_ocr(self) -> Any:
        if self._ocr is None:
            self._ocr = _load_paddleocr()
        return self._ocr


def _load_paddleocr() -> Any:
    _prepare_paddleocr_environment()
    finder = _BlockAlbumentationsPytorchFinder()
    sys.meta_path.insert(0, finder)
    try:
        from paddleocr import PaddleOCR
    except ModuleNotFoundError as exc:
        missing_module = exc.name or "paddleocr"
        raise UpstreamUnavailableError(
            f"PaddleOCR runtime is unavailable. Missing Python module: {missing_module}."
        ) from exc
    except OSError as exc:
        raise UpstreamUnavailableError(
            f"PaddleOCR runtime could not be loaded: {exc}."
        ) from exc
    finally:
        if finder in sys.meta_path:
            sys.meta_path.remove(finder)

    try:
        return PaddleOCR(
            lang="en",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
        )
    except RuntimeError as exc:
        raise UpstreamUnavailableError(
            f"PaddleOCR model files are unavailable: {exc}."
        ) from exc


class _BlockAlbumentationsPytorchFinder(importlib.abc.MetaPathFinder):
    def find_spec(
        self,
        fullname: str,
        path: object | None = None,
        target: object | None = None,
    ) -> object | None:
        del path, target
        if fullname == "albumentations.pytorch" or fullname.startswith(
            "albumentations.pytorch."
        ):
            raise ImportError("Skipping optional albumentations PyTorch integration.")
        return None


def _prepare_paddleocr_environment() -> None:
    cache_dir = Path(__file__).resolve().parents[2] / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["HOME"] = str(cache_dir)
    os.environ["USERPROFILE"] = str(cache_dir)
    os.environ.setdefault("NO_ALBUMENTATIONS_UPDATE", "1")
    os.environ.setdefault("FLAGS_use_mkldnn", "0")
    os.environ.setdefault("FLAGS_use_onednn", "0")
    os.environ.setdefault("FLAGS_enable_pir_api", "0")


def _extract_text_lines(result: Any) -> list[str]:
    lines: list[str] = []
    if not result:
        return lines

    for page in result:
        if isinstance(page, dict):
            rec_texts = page.get("rec_texts")
            if isinstance(rec_texts, list):
                lines.extend(
                    str(text).strip() for text in rec_texts if str(text).strip()
                )
            continue
        if not isinstance(page, list):
            continue
        for item in page:
            text = _text_from_ocr_item(item)
            if text:
                lines.append(text)
    return lines


def _text_from_ocr_item(item: Any) -> str | None:
    if isinstance(item, str):
        return item.strip() or None
    if not isinstance(item, list | tuple) or len(item) < 2:
        return None
    candidate = item[1]
    if isinstance(candidate, str):
        return candidate.strip() or None
    if isinstance(candidate, list | tuple) and candidate:
        text = candidate[0]
        return str(text).strip() or None
    return None


image_ocr_service = ImageOcrService()
