from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory


@dataclass(frozen=True)
class PdfTextExtractionResult:
    text: str
    pages_processed: int | None = None


class PdfTextExtractionService:
    def __init__(
        self,
        *,
        converter: Callable[..., object] | None = None,
        min_text_length: int = 20,
    ) -> None:
        self._converter = converter
        self._min_text_length = min_text_length

    def extract_text(self, pdf_path: Path) -> PdfTextExtractionResult:
        converter = self._converter or _load_opendataloader_converter()
        with TemporaryDirectory(prefix="qima_lab_pdf_") as output_dir:
            output_path = Path(output_dir)
            converter(
                input_path=str(pdf_path),
                output_dir=str(output_path),
                format="markdown,text",
                hybrid="off",
                quiet=True,
            )
            extracted_file = _find_best_output_file(output_path)
            text = extracted_file.read_text(encoding="utf-8", errors="replace") if extracted_file else ""
            return PdfTextExtractionResult(
                text=text.strip(),
                pages_processed=None,
            )

    def has_usable_text(self, text: str) -> bool:
        return len("".join(text.split())) >= self._min_text_length


def _load_opendataloader_converter() -> Callable[..., object]:
    import opendataloader_pdf

    return opendataloader_pdf.convert


def _find_best_output_file(output_dir: Path) -> Path | None:
    markdown_files = [
        path
        for path in output_dir.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".md", ".markdown"}
    ]
    if markdown_files:
        return max(markdown_files, key=lambda path: path.stat().st_size)

    text_files = [
        path
        for path in output_dir.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".txt", ".text"}
    ]
    if text_files:
        return max(text_files, key=lambda path: path.stat().st_size)

    return None


pdf_text_extraction_service = PdfTextExtractionService()
