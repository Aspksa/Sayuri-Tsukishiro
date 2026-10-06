from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Callable


SPATIAL_ENGINE_VERSION = "0.8.0"
MAX_PAGES = 120
MAX_OCR_PAGES = 24
MAX_NATIVE_CHARS_PER_PAGE = 120_000
MAX_LINES_PER_PAGE = 4_000
OCR_DPI = 220
OCR_TIMEOUT_SECONDS = 75
OCR_LANGUAGES = "rus+eng"
OCR_MIN_NATIVE_CHARS = 80

SIGNATURE_KEYWORDS = (
    "подпись", "подписал", "подписано", "директор", "руководитель",
    "исполнитель", "м.п.", "мп", "печать",
)
STAMP_KEYWORDS = ("печать", "м.п.", "мп")


class SpatialDNAEngine:
    """PDFium + Tesseract spatial layer. No invented coordinates or OCR success."""

    def __init__(
        self,
        *,
        tessdata_path: Path | None = None,
        tesseract_path: Path | None = None,
        pdfium_module: Any | None = None,
        image_module: Any | None = None,
        ocr_runner: Callable[[Any, Path, int], str] | None = None,
    ) -> None:
        self.tessdata_path = tessdata_path
        self.tesseract_path = tesseract_path
        self._pdfium = pdfium_module
        self._image = image_module
        self._ocr_runner = ocr_runner
        self._pdfium_error: str | None = None
        self._image_error: str | None = None

        if self._pdfium is None:
            try:
                import pypdfium2 as pdfium  # type: ignore
                self._pdfium = pdfium
            except Exception as exc:  # pragma: no cover - runtime dependent.
                self._pdfium_error = f"{type(exc).__name__}: {exc}"

        if self._image is None:
            try:
                from PIL import Image  # type: ignore
                self._image = Image
            except Exception as exc:  # pragma: no cover - runtime dependent.
                self._image_error = f"{type(exc).__name__}: {exc}"

    @staticmethod
    def _package_version(name: str) -> str | None:
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return None

    def _resolve_tessdata(self) -> Path | None:
        candidates: list[Path] = []
        if self.tessdata_path:
            candidates.append(self.tessdata_path)
        for key in ("SAYURI_TESSDATA", "TESSDATA_PREFIX"):
            value = os.environ.get(key)
            if value:
                candidates.append(Path(value))
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        return None

    def _resolve_tesseract(self) -> Path | None:
        candidates: list[Path] = []
        if self.tesseract_path:
            candidates.append(self.tesseract_path)
        configured = os.environ.get("SAYURI_TESSERACT")
        if configured:
            candidates.append(Path(configured))
        found = shutil.which("tesseract")
        if found:
            candidates.append(Path(found))
        if os.name == "nt":
            for env_name in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
                base = os.environ.get(env_name)
                if base:
                    candidates.append(Path(base) / "Tesseract-OCR" / "tesseract.exe")
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    def capabilities(self) -> dict[str, Any]:
        tessdata = self._resolve_tessdata()
        tesseract = self._resolve_tesseract()
        languages = []
        if tessdata:
            for language in ("rus", "eng"):
                if (tessdata / f"{language}.traineddata").is_file():
                    languages.append(language)
        return {
            "engine_version": SPATIAL_ENGINE_VERSION,
            "pdfium_available": self._pdfium is not None,
            "pdfium_version": self._package_version("pypdfium2"),
            "pdfium_import_error": self._pdfium_error,
            "pillow_available": self._image is not None,
            "pillow_version": self._package_version("Pillow"),
            "pillow_import_error": self._image_error,
            "tesseract_available": tesseract is not None or self._ocr_runner is not None,
            "tesseract_path": str(tesseract) if tesseract else None,
            "tessdata_path": str(tessdata) if tessdata else None,
            "ocr_languages": languages,
            "ocr_ready": (
                self._image is not None
                and (tesseract is not None or self._ocr_runner is not None)
                and {"rus", "eng"} <= set(languages)
            ),
            "ocr_language_spec": OCR_LANGUAGES,
            "ocr_dpi": OCR_DPI,
            "ocr_timeout_seconds": OCR_TIMEOUT_SECONDS,
            "max_pages": MAX_PAGES,
            "max_ocr_pages": MAX_OCR_PAGES,
        }

    @staticmethod
    def _bbox_payload(
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        *,
        page_width: float,
        page_height: float,
        coordinate_space: str = "points",
    ) -> dict[str, Any]:
        safe_width = max(float(page_width), 1.0)
        safe_height = max(float(page_height), 1.0)
        return {
            "space": coordinate_space,
            "values": [
                round(float(x0), 3), round(float(y0), 3),
                round(float(x1), 3), round(float(y1), 3),
            ],
            "normalized": [
                round(max(0.0, min(1.0, float(x0) / safe_width)), 6),
                round(max(0.0, min(1.0, float(y0) / safe_height)), 6),
                round(max(0.0, min(1.0, float(x1) / safe_width)), 6),
                round(max(0.0, min(1.0, float(y1) / safe_height)), 6),
            ],
        }

    @staticmethod
    def _union_bbox(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
        if not boxes:
            return 0.0, 0.0, 0.0, 0.0
        return (
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        )

    @staticmethod
    def _region_role(y0: float, y1: float, page_height: float) -> str:
        if page_height <= 0:
            return "body"
        if y1 <= page_height * 0.14:
            return "header"
        if y0 >= page_height * 0.86:
            return "footer"
        return "body"

    @staticmethod
    def _page_quality(
        text: str,
        *,
        extraction_method: str,
        average_ocr_confidence: float | None,
        line_count: int,
    ) -> dict[str, Any]:
        stripped = text.strip()
        chars = len(stripped)
        if not stripped:
            return {
                "score": 0,
                "characters": 0,
                "printable_ratio": 0.0,
                "alnum_ratio": 0.0,
                "average_ocr_confidence": average_ocr_confidence,
                "method": "combined_text_quality",
            }
        printable = sum(1 for char in stripped if char.isprintable()) / max(1, chars)
        alnum = sum(1 for char in stripped if char.isalnum()) / max(1, chars)
        length_score = min(1.0, math.log10(max(chars, 10)) / 3.0)
        line_score = min(1.0, line_count / 15.0)
        ocr_score = (
            max(0.0, min(1.0, float(average_ocr_confidence) / 100.0))
            if average_ocr_confidence is not None
            else 1.0
        )
        score = (
            printable * 0.25
            + alnum * 0.25
            + length_score * 0.20
            + line_score * 0.10
            + ocr_score * 0.20
        )
        return {
            "score": max(0, min(100, int(round(score * 100)))),
            "characters": chars,
            "printable_ratio": round(printable, 4),
            "alnum_ratio": round(alnum, 4),
            "average_ocr_confidence": (
                round(float(average_ocr_confidence), 2)
                if average_ocr_confidence is not None
                else None
            ),
            "extraction_method": extraction_method,
            "method": "combined_text_quality",
        }

    @staticmethod
    def _needs_ocr(native_text: str, image_like_objects: int) -> tuple[bool, str]:
        chars = len(native_text.strip())
        if chars == 0:
            return True, "no_native_text"
        if chars < OCR_MIN_NATIVE_CHARS and image_like_objects:
            return True, "little_text_with_images"
        if chars < OCR_MIN_NATIVE_CHARS:
            return True, "sparse_native_text"
        return False, "native_text_sufficient"

    @staticmethod
    def _tokenize_native_line(
        chars: list[dict[str, Any]],
        *,
        page_width: float,
        page_height: float,
    ) -> tuple[str, list[dict[str, Any]]]:
        text = "".join(str(item["char"]) for item in chars)
        words = []
        current: list[dict[str, Any]] = []
        for item in chars + [{"char": " ", "bbox_tuple": (0, 0, 0, 0)}]:
            char = str(item["char"])
            if char.isspace():
                if current:
                    word_text = "".join(str(value["char"]) for value in current)
                    bbox = SpatialDNAEngine._union_bbox([value["bbox_tuple"] for value in current])
                    words.append({
                        "text": word_text,
                        "bbox": SpatialDNAEngine._bbox_payload(
                            *bbox,
                            page_width=page_width,
                            page_height=page_height,
                        ),
                        "confidence": None,
                    })
                    current = []
            else:
                current.append(item)
        return text.strip(), words

    def _native_lines(
        self,
        textpage: Any,
        *,
        page_number: int,
        page_width: float,
        page_height: float,
        global_line_start: int,
    ) -> tuple[list[dict[str, Any]], str, int, bool]:
        try:
            char_count = min(int(textpage.count_chars()), MAX_NATIVE_CHARS_PER_PAGE)
        except Exception:
            return [], "", global_line_start, False

        chars = []
        truncated = False
        try:
            full_count = int(textpage.count_chars())
            truncated = full_count > char_count
        except Exception:
            pass

        for index in range(char_count):
            try:
                char = textpage.get_text_range(index=index, count=1)
                if not char:
                    continue
                left, bottom, right, top = textpage.get_charbox(index)
            except Exception:
                continue
            # PDF canvas uses bottom-left origin. Convert to top-left for the DNA.
            bbox = (
                float(left),
                float(page_height - top),
                float(right),
                float(page_height - bottom),
            )
            chars.append({"char": char, "bbox_tuple": bbox})

        lines_raw: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        current_y: float | None = None
        tolerance = max(2.5, page_height * 0.004)
        for item in chars:
            char = str(item["char"])
            box = item["bbox_tuple"]
            center_y = (box[1] + box[3]) / 2
            explicit_break = "\n" in char or "\r" in char
            if current and (
                explicit_break
                or (current_y is not None and abs(center_y - current_y) > tolerance)
            ):
                lines_raw.append(current)
                current = []
                current_y = None
            clean_char = char.replace("\r", "").replace("\n", "")
            if clean_char:
                copied = dict(item)
                copied["char"] = clean_char
                current.append(copied)
                current_y = center_y if current_y is None else (current_y * 0.85 + center_y * 0.15)
            if explicit_break and current:
                lines_raw.append(current)
                current = []
                current_y = None
            if len(lines_raw) >= MAX_LINES_PER_PAGE:
                truncated = True
                break
        if current and len(lines_raw) < MAX_LINES_PER_PAGE:
            lines_raw.append(current)

        lines = []
        texts = []
        global_line = global_line_start
        for line_index, line_chars in enumerate(lines_raw, start=1):
            line_chars.sort(key=lambda item: item["bbox_tuple"][0])
            text, words = self._tokenize_native_line(
                line_chars,
                page_width=page_width,
                page_height=page_height,
            )
            if not text:
                continue
            bbox = self._union_bbox([item["bbox_tuple"] for item in line_chars])
            global_line += 1
            lines.append({
                "id": f"p{page_number}-native-l{line_index}",
                "page": page_number,
                "global_line": global_line,
                "text": text,
                "bbox": self._bbox_payload(
                    *bbox,
                    page_width=page_width,
                    page_height=page_height,
                ),
                "words": words,
                "extraction_method": "native",
                "region": self._region_role(bbox[1], bbox[3], page_height),
            })
            texts.append(text)
        return lines, "\n".join(texts), global_line, truncated

    @staticmethod
    def _parse_tsv(tsv: str) -> list[dict[str, Any]]:
        rows = []
        lines = tsv.splitlines()
        if not lines:
            return rows
        header = lines[0].split("\t")
        index = {name: pos for pos, name in enumerate(header)}
        required = {"level", "block_num", "par_num", "line_num", "word_num", "left", "top", "width", "height", "conf", "text"}
        if not required <= set(index):
            return rows
        for raw in lines[1:]:
            parts = raw.split("\t")
            if len(parts) < len(header):
                parts.extend([""] * (len(header) - len(parts)))
            text = parts[index["text"]].strip()
            if not text:
                continue
            try:
                level = int(parts[index["level"]])
                if level != 5:
                    continue
                rows.append({
                    "block": int(parts[index["block_num"]]),
                    "paragraph": int(parts[index["par_num"]]),
                    "line": int(parts[index["line_num"]]),
                    "word": int(parts[index["word_num"]]),
                    "left": float(parts[index["left"]]),
                    "top": float(parts[index["top"]]),
                    "width": float(parts[index["width"]]),
                    "height": float(parts[index["height"]]),
                    "confidence": float(parts[index["conf"]]),
                    "text": text,
                })
            except (TypeError, ValueError):
                continue
        return rows

    def _run_tesseract(self, image: Any, tessdata: Path, page_number: int) -> str:
        if self._ocr_runner is not None:
            return self._ocr_runner(image, tessdata, page_number)
        executable = self._resolve_tesseract()
        if executable is None:
            raise RuntimeError("Tesseract OCR не найден.")
        with tempfile.TemporaryDirectory(prefix="sayuri-ocr-") as tmp:
            image_path = Path(tmp) / f"page-{page_number}.png"
            image.save(image_path, format="PNG")
            command = [
                str(executable),
                str(image_path),
                "stdout",
                "--tessdata-dir",
                str(tessdata),
                "-l",
                OCR_LANGUAGES,
                "--psm",
                "3",
                "tsv",
            ]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=OCR_TIMEOUT_SECONDS,
                check=False,
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if os.name == "nt"
                    else 0
                ),
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"Tesseract завершился с кодом {result.returncode}: {result.stderr[-500:]}"
                )
            return result.stdout

    def _ocr_lines(
        self,
        image: Any,
        *,
        tessdata: Path,
        page_number: int,
        page_width: float,
        page_height: float,
        pixel_width: float,
        pixel_height: float,
        global_line_start: int,
    ) -> tuple[list[dict[str, Any]], str, int, float | None]:
        tsv = self._run_tesseract(image, tessdata, page_number)
        words = self._parse_tsv(tsv)
        grouped: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
        for word in words:
            grouped[(word["block"], word["paragraph"], word["line"])].append(word)

        lines = []
        texts = []
        global_line = global_line_start
        confidences = []
        x_scale = page_width / max(pixel_width, 1.0)
        y_scale = page_height / max(pixel_height, 1.0)

        for line_index, (_, line_words) in enumerate(sorted(grouped.items()), start=1):
            line_words.sort(key=lambda item: item["left"])
            text = " ".join(str(word["text"]) for word in line_words).strip()
            if not text:
                continue
            boxes = []
            word_payloads = []
            for word in line_words:
                x0 = word["left"] * x_scale
                y0 = word["top"] * y_scale
                x1 = (word["left"] + word["width"]) * x_scale
                y1 = (word["top"] + word["height"]) * y_scale
                boxes.append((x0, y0, x1, y1))
                confidence = max(-1.0, min(100.0, float(word["confidence"])))
                if confidence >= 0:
                    confidences.append(confidence)
                word_payloads.append({
                    "text": word["text"],
                    "confidence": confidence if confidence >= 0 else None,
                    "bbox": self._bbox_payload(
                        x0, y0, x1, y1,
                        page_width=page_width,
                        page_height=page_height,
                    ),
                })
            bbox = self._union_bbox(boxes)
            global_line += 1
            lines.append({
                "id": f"p{page_number}-ocr-l{line_index}",
                "page": page_number,
                "global_line": global_line,
                "text": text,
                "bbox": self._bbox_payload(
                    *bbox,
                    page_width=page_width,
                    page_height=page_height,
                ),
                "words": word_payloads,
                "extraction_method": "ocr",
                "region": self._region_role(bbox[1], bbox[3], page_height),
            })
            texts.append(text)

        average = sum(confidences) / len(confidences) if confidences else None
        return lines, "\n".join(texts), global_line, average

    @staticmethod
    def _table_candidates(
        lines: list[dict[str, Any]],
        *,
        page_number: int,
    ) -> list[dict[str, Any]]:
        candidates = []
        run: list[dict[str, Any]] = []
        for line in lines + [{"words": []}]:
            words = line.get("words") or []
            if len(words) >= 2:
                run.append(line)
                continue
            if len(run) >= 2:
                x_sets = [
                    [float(word["bbox"]["normalized"][0]) for word in row.get("words") or []]
                    for row in run
                ]
                aligned = 0
                for left in x_sets[0]:
                    if sum(any(abs(left - x) <= 0.035 for x in row) for row in x_sets[1:]) >= max(1, len(x_sets) - 2):
                        aligned += 1
                if aligned >= 2:
                    boxes = [
                        tuple(float(value) for value in row["bbox"]["values"])
                        for row in run
                    ]
                    bbox = SpatialDNAEngine._union_bbox(boxes)
                    candidates.append({
                        "id": f"p{page_number}-table-candidate-{len(candidates) + 1}",
                        "page": page_number,
                        "status": "candidate",
                        "basis": "aligned_text_columns",
                        "confidence": min(0.88, 0.55 + aligned * 0.08 + len(run) * 0.02),
                        "row_line_ids": [row["id"] for row in run],
                        "row_count": len(run),
                        "aligned_columns": aligned,
                        "bbox_points": list(bbox),
                    })
            run = []
        return candidates[:30]

    @staticmethod
    def _visual_candidates(
        lines: list[dict[str, Any]],
        objects: list[dict[str, Any]],
        *,
        page_number: int,
        page_height: float,
    ) -> list[dict[str, Any]]:
        candidates = []
        for line in lines:
            lowered = str(line.get("text") or "").casefold().replace("ё", "е")
            if any(keyword.replace("ё", "е") in lowered for keyword in SIGNATURE_KEYWORDS):
                is_stamp = any(keyword.replace("ё", "е") in lowered for keyword in STAMP_KEYWORDS)
                candidates.append({
                    "id": f"p{page_number}-candidate-{len(candidates) + 1}",
                    "kind": "stamp_zone_candidate" if is_stamp else "signature_zone_candidate",
                    "status": "candidate",
                    "page": page_number,
                    "bbox": line.get("bbox"),
                    "confidence": 0.60 if is_stamp else 0.64,
                    "basis": "document_keyword",
                    "evidence_line_id": line.get("id"),
                })
        for obj in objects[:250]:
            bbox = obj.get("bbox")
            if not bbox:
                continue
            x0, y0, x1, y1 = bbox
            width = max(0.0, x1 - x0)
            height = max(0.0, y1 - y0)
            if not width or not height:
                continue
            ratio = width / height
            if 0.70 <= ratio <= 1.42 and 24 <= width <= 190 and 24 <= height <= 190 and y0 >= page_height * 0.35:
                candidates.append({
                    "id": f"p{page_number}-shape-{len(candidates) + 1}",
                    "kind": "stamp_shape_candidate",
                    "status": "hypothesis",
                    "page": page_number,
                    "bbox_points": [round(value, 3) for value in bbox],
                    "confidence": 0.40,
                    "basis": "near_square_or_circular_page_object",
                    "note": "Геометрическая гипотеза; не считается подтверждённой печатью.",
                })
        return candidates[:80]

    def _pdf_objects(self, page: Any, *, page_height: float) -> list[dict[str, Any]]:
        objects = []
        try:
            iterator = page.get_objects()
        except Exception:
            return objects
        try:
            for index, obj in enumerate(iterator):
                if index >= 400:
                    break
                try:
                    left, bottom, right, top = obj.get_bounds()
                except Exception:
                    continue
                objects.append({
                    "index": index,
                    "type": str(getattr(obj, "type", "unknown")),
                    "bbox": (
                        float(left),
                        float(page_height - top),
                        float(right),
                        float(page_height - bottom),
                    ),
                })
        except Exception:
            return objects
        return objects

    def _render_pdf_page(self, page: Any) -> Any:
        scale = OCR_DPI / 72.0
        bitmap = page.render(scale=scale, rotation=0)
        image = bitmap.to_pil()
        close = getattr(bitmap, "close", None)
        if callable(close):
            close()
        return image

    def render_evidence_focus(
        self,
        path: Path,
        *,
        content_type: str,
        suffix: str,
        page_number: int,
        bbox: dict[str, Any],
        max_width: int = 1600,
    ) -> dict[str, Any]:
        """Render a document page/image and highlight an exact normalized bbox.

        Coordinates are accepted only from a stored SpatialDNA locator. Callers must
        resolve the locator by fact_id before invoking this method.
        """
        normalized = bbox.get("normalized") if isinstance(bbox, dict) else None
        if not isinstance(normalized, list) or len(normalized) != 4:
            raise ValueError("Для evidence-focus нужен нормализованный bbox.")
        try:
            x0, y0, x1, y1 = [float(value) for value in normalized]
        except (TypeError, ValueError) as exc:
            raise ValueError("Некорректные координаты evidence bbox.") from exc
        coords = [max(0.0, min(1.0, value)) for value in (x0, y0, x1, y1)]
        x0, y0, x1, y1 = coords
        if x1 <= x0 or y1 <= y0:
            raise ValueError("Evidence bbox имеет нулевой размер.")
        safe_page = max(1, int(page_number or 1))
        safe_width = min(max(int(max_width), 640), 2200)
        suffix = suffix.casefold()

        image = None
        document = None
        page = None
        bitmap = None
        try:
            if content_type == "application/pdf" or suffix == ".pdf":
                if self._pdfium is None:
                    raise RuntimeError("PDFium недоступен для evidence-focus.")
                document = self._pdfium.PdfDocument(str(path))
                if safe_page > len(document):
                    raise ValueError("Страница evidence отсутствует в документе.")
                page = document[safe_page - 1]
                page_width, _page_height = [float(value) for value in page.get_size()]
                scale = min(2.4, max(1.0, safe_width / max(page_width, 1.0)))
                bitmap = page.render(scale=scale, rotation=0)
                image = bitmap.to_pil()
            elif content_type.startswith("image/") or suffix in {
                ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp",
            }:
                if self._image is None:
                    raise RuntimeError("Pillow недоступен для evidence-focus.")
                image = self._image.open(path)
                safe_page = 1
            else:
                raise ValueError("Формат не поддерживает визуальную spatial-подсветку.")

            convert = getattr(image, "convert", None)
            if callable(convert):
                converted = convert("RGB")
                if converted is not image:
                    close_original = getattr(image, "close", None)
                    if callable(close_original):
                        close_original()
                    image = converted

            width, height = [int(value) for value in image.size]
            if width > safe_width:
                target_height = max(1, round(height * safe_width / width))
                resize = getattr(image, "resize", None)
                if callable(resize):
                    try:
                        from PIL import Image as PILImage  # type: ignore
                        resampling = getattr(getattr(PILImage, "Resampling", PILImage), "LANCZOS", 1)
                    except Exception:
                        resampling = 1
                    resized = resize((safe_width, target_height), resampling)
                    if resized is not image:
                        close_original = getattr(image, "close", None)
                        if callable(close_original):
                            close_original()
                        image = resized
                    width, height = safe_width, target_height

            try:
                from PIL import ImageDraw  # type: ignore
            except Exception as exc:  # pragma: no cover - runtime dependency.
                raise RuntimeError("Pillow ImageDraw недоступен для evidence-focus.") from exc

            left = max(0, min(width - 1, round(x0 * width)))
            top = max(0, min(height - 1, round(y0 * height)))
            right = max(left + 1, min(width, round(x1 * width)))
            bottom = max(top + 1, min(height, round(y1 * height)))
            pad = max(3, round(min(width, height) * 0.006))
            box = (
                max(0, left - pad),
                max(0, top - pad),
                min(width - 1, right + pad),
                min(height - 1, bottom + pad),
            )

            draw = ImageDraw.Draw(image, "RGBA")
            outline_width = max(3, round(min(width, height) * 0.004))
            draw.rectangle(box, fill=(255, 220, 70, 72), outline=(218, 149, 0, 255), width=outline_width)

            from io import BytesIO
            buffer = BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            return {
                "content_type": "image/png",
                "body": buffer.getvalue(),
                "page": safe_page,
                "width": width,
                "height": height,
                "bbox": {
                    "normalized": [round(value, 6) for value in (x0, y0, x1, y1)],
                },
            }
        finally:
            for resource in (image, bitmap, page, document):
                close = getattr(resource, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass

    def _extract_pdf(
        self,
        path: Path,
        *,
        force_ocr: bool,
        max_pages: int,
    ) -> dict[str, Any]:
        capabilities = self.capabilities()
        if self._pdfium is None:
            return self._empty_result("unavailable", "pdfium_unavailable", capabilities)
        try:
            document = self._pdfium.PdfDocument(str(path))
        except Exception as exc:
            result = self._empty_result("error", "open_failed", capabilities)
            result["error"] = f"{type(exc).__name__}: {exc}"
            return result

        pages = []
        line_map = []
        combined_lines = []
        global_line = 0
        ocr_used = 0
        ocr_requested = 0
        ocr_failures = []
        tessdata = self._resolve_tessdata()
        source_page_count = len(document)
        selected_count = min(source_page_count, max(1, int(max_pages)))

        try:
            for page_index in range(selected_count):
                page_number = page_index + 1
                page = document[page_index]
                page_width, page_height = [float(value) for value in page.get_size()]
                rotation = 0
                get_rotation = getattr(page, "get_rotation", None)
                if callable(get_rotation):
                    try:
                        rotation = int(get_rotation())
                    except Exception:
                        rotation = 0

                objects = self._pdf_objects(page, page_height=page_height)
                try:
                    textpage = page.get_textpage()
                    native_lines, native_text, global_line_after_native, native_truncated = self._native_lines(
                        textpage,
                        page_number=page_number,
                        page_width=page_width,
                        page_height=page_height,
                        global_line_start=global_line,
                    )
                    close_textpage = getattr(textpage, "close", None)
                    if callable(close_textpage):
                        close_textpage()
                except Exception:
                    native_lines, native_text, global_line_after_native, native_truncated = [], "", global_line, False

                image_like = sum(
                    1 for obj in objects
                    if "image" in str(obj.get("type", "")).casefold()
                )
                needs_ocr, ocr_reason = self._needs_ocr(native_text, image_like)
                request_ocr = bool(force_ocr or needs_ocr)
                lines = native_lines
                text = native_text
                method = "native"
                average_ocr_confidence = None
                ocr_error = None
                page_global_line = global_line_after_native

                if request_ocr:
                    ocr_requested += 1
                    if ocr_used >= MAX_OCR_PAGES:
                        ocr_error = "ocr_page_budget_exhausted"
                    elif not capabilities.get("ocr_ready") or tessdata is None:
                        ocr_error = "ocr_runtime_not_ready"
                    else:
                        try:
                            image = self._render_pdf_page(page)
                            pixel_width, pixel_height = image.size
                            ocr_lines, ocr_text, page_global_line, average_ocr_confidence = self._ocr_lines(
                                image,
                                tessdata=tessdata,
                                page_number=page_number,
                                page_width=page_width,
                                page_height=page_height,
                                pixel_width=float(pixel_width),
                                pixel_height=float(pixel_height),
                                global_line_start=global_line,
                            )
                            close_image = getattr(image, "close", None)
                            if callable(close_image):
                                close_image()
                            if ocr_lines:
                                lines = ocr_lines
                                text = ocr_text
                                method = "ocr"
                                ocr_used += 1
                        except Exception as exc:
                            ocr_error = f"{type(exc).__name__}: {exc}"

                if ocr_error:
                    ocr_failures.append({
                        "page": page_number,
                        "reason": ocr_reason,
                        "error": ocr_error,
                    })

                # If OCR replaced native text, the global line counter must follow chosen output.
                global_line = page_global_line if method == "ocr" else global_line_after_native
                tables = self._table_candidates(lines, page_number=page_number)
                candidates = self._visual_candidates(
                    lines,
                    objects,
                    page_number=page_number,
                    page_height=page_height,
                )
                quality = self._page_quality(
                    text,
                    extraction_method=method,
                    average_ocr_confidence=average_ocr_confidence,
                    line_count=len(lines),
                )
                page_material = json.dumps(
                    {
                        "page": page_number,
                        "size": [round(page_width, 3), round(page_height, 3)],
                        "rotation": rotation,
                        "method": method,
                        "lines": [
                            {
                                "text": line.get("text"),
                                "bbox": line.get("bbox"),
                            }
                            for line in lines
                        ],
                        "tables": tables,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                pages.append({
                    "page": page_number,
                    "width_points": round(page_width, 3),
                    "height_points": round(page_height, 3),
                    "rotation": rotation,
                    "extraction_method": method,
                    "ocr_requested": request_ocr,
                    "ocr_reason": ocr_reason,
                    "ocr_error": ocr_error,
                    "native_text_characters": len(native_text.strip()),
                    "native_truncated": native_truncated,
                    "lines": lines,
                    "table_candidates": tables,
                    "visual_candidates": candidates,
                    "quality": quality,
                    "spatial_sha256": sha256(page_material.encode("utf-8")).hexdigest(),
                })
                line_map.extend({
                    "global_line": line["global_line"],
                    "page": line["page"],
                    "line_id": line["id"],
                    "bbox": line["bbox"],
                    "text": line["text"],
                    "extraction_method": line["extraction_method"],
                } for line in lines)
                combined_lines.extend(line["text"] for line in lines)
        finally:
            close = getattr(document, "close", None)
            if callable(close):
                close()

        return self._finalize(
            capabilities=capabilities,
            pages=pages,
            line_map=line_map,
            combined_lines=combined_lines,
            source_page_count=source_page_count,
            ocr_requested=ocr_requested,
            ocr_used=ocr_used,
            ocr_failures=ocr_failures,
            force_ocr=force_ocr,
        )

    def _extract_image(
        self,
        path: Path,
        *,
        force_ocr: bool,
    ) -> dict[str, Any]:
        capabilities = self.capabilities()
        if self._image is None:
            return self._empty_result("unavailable", "pillow_unavailable", capabilities)
        try:
            image = self._image.open(path)
            image.load()
        except Exception as exc:
            result = self._empty_result("error", "image_open_failed", capabilities)
            result["error"] = f"{type(exc).__name__}: {exc}"
            return result

        width, height = [float(value) for value in image.size]
        lines = []
        text = ""
        average_ocr_confidence = None
        ocr_error = None
        tessdata = self._resolve_tessdata()
        if capabilities.get("ocr_ready") and tessdata is not None:
            try:
                lines, text, _, average_ocr_confidence = self._ocr_lines(
                    image,
                    tessdata=tessdata,
                    page_number=1,
                    page_width=width,
                    page_height=height,
                    pixel_width=width,
                    pixel_height=height,
                    global_line_start=0,
                )
            except Exception as exc:
                ocr_error = f"{type(exc).__name__}: {exc}"
        else:
            ocr_error = "ocr_runtime_not_ready"

        close = getattr(image, "close", None)
        if callable(close):
            close()
        tables = self._table_candidates(lines, page_number=1)
        candidates = self._visual_candidates(
            lines,
            [],
            page_number=1,
            page_height=height,
        )
        quality = self._page_quality(
            text,
            extraction_method="ocr" if lines else "none",
            average_ocr_confidence=average_ocr_confidence,
            line_count=len(lines),
        )
        page_material = json.dumps(
            {"size": [width, height], "lines": lines, "tables": tables},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        page = {
            "page": 1,
            "width_pixels": int(width),
            "height_pixels": int(height),
            "rotation": 0,
            "extraction_method": "ocr" if lines else "none",
            "ocr_requested": True,
            "ocr_reason": "image_requires_ocr",
            "ocr_error": ocr_error,
            "native_text_characters": 0,
            "native_truncated": False,
            "lines": lines,
            "table_candidates": tables,
            "visual_candidates": candidates,
            "quality": quality,
            "spatial_sha256": sha256(page_material.encode("utf-8")).hexdigest(),
        }
        return self._finalize(
            capabilities=capabilities,
            pages=[page],
            line_map=[
                {
                    "global_line": line["global_line"],
                    "page": 1,
                    "line_id": line["id"],
                    "bbox": line["bbox"],
                    "text": line["text"],
                    "extraction_method": line["extraction_method"],
                }
                for line in lines
            ],
            combined_lines=[line["text"] for line in lines],
            source_page_count=1,
            ocr_requested=1,
            ocr_used=1 if lines else 0,
            ocr_failures=(
                [{"page": 1, "reason": "image_requires_ocr", "error": ocr_error}]
                if ocr_error else []
            ),
            force_ocr=True,
        )

    @staticmethod
    def _empty_result(status: str, reason: str, capabilities: dict[str, Any]) -> dict[str, Any]:
        return {
            "engine_version": SPATIAL_ENGINE_VERSION,
            "status": status,
            "reason": reason,
            "capabilities": capabilities,
            "pages": [],
            "line_map": [],
            "combined_text": "",
            "ocr": {
                "requested_pages": 0,
                "used_pages": 0,
                "failures": [],
                "coverage_percent": 0.0,
            },
            "tables": {"candidate_count": 0},
            "visual_candidates": {"count": 0},
            "quality": {"score": 0},
        }

    @staticmethod
    def _finalize(
        *,
        capabilities: dict[str, Any],
        pages: list[dict[str, Any]],
        line_map: list[dict[str, Any]],
        combined_lines: list[str],
        source_page_count: int,
        ocr_requested: int,
        ocr_used: int,
        ocr_failures: list[dict[str, Any]],
        force_ocr: bool,
    ) -> dict[str, Any]:
        quality_scores = [int(page.get("quality", {}).get("score") or 0) for page in pages]
        table_count = sum(len(page.get("table_candidates") or []) for page in pages)
        candidate_count = sum(len(page.get("visual_candidates") or []) for page in pages)
        spatial_material = json.dumps(
            {
                "pages": [
                    {
                        "page": page["page"],
                        "sha256": page["spatial_sha256"],
                        "method": page["extraction_method"],
                    }
                    for page in pages
                ],
                "line_count": len(line_map),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return {
            "engine_version": SPATIAL_ENGINE_VERSION,
            "status": "ready",
            "force_ocr": bool(force_ocr),
            "capabilities": capabilities,
            "page_count": len(pages),
            "source_page_count": source_page_count,
            "truncated": source_page_count > len(pages),
            "pages": pages,
            "line_map": line_map,
            "combined_text": "\n".join(combined_lines),
            "ocr": {
                "requested_pages": ocr_requested,
                "used_pages": ocr_used,
                "failures": ocr_failures,
                "coverage_percent": round(ocr_used / max(1, ocr_requested) * 100, 2) if ocr_requested else 100.0,
                "page_budget": MAX_OCR_PAGES,
            },
            "tables": {
                "candidate_count": table_count,
                "policy": "Геометрический кандидат таблицы не считается подтверждённой структурой без дополнительной проверки.",
            },
            "visual_candidates": {
                "count": candidate_count,
                "policy": "Кандидаты подписи/печати не считаются подтверждёнными фактами.",
            },
            "quality": {
                "score": int(round(sum(quality_scores) / max(1, len(quality_scores)))),
                "page_scores": quality_scores,
                "method": "page_text_and_ocr_quality",
            },
            "spatial_sha256": sha256(spatial_material.encode("utf-8")).hexdigest(),
        }

    def extract(
        self,
        path: Path,
        *,
        content_type: str,
        suffix: str,
        force_ocr: bool = False,
        max_pages: int = MAX_PAGES,
    ) -> dict[str, Any]:
        capabilities = self.capabilities()
        suffix = suffix.casefold()
        if content_type == "application/pdf" or suffix == ".pdf":
            return self._extract_pdf(path, force_ocr=force_ocr, max_pages=max_pages)
        if content_type.startswith("image/") or suffix in {
            ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp",
        }:
            return self._extract_image(path, force_ocr=force_ocr)
        return self._empty_result("not_applicable", "format_without_page_geometry", capabilities)

    @staticmethod
    def analysis_preview(original_preview: dict[str, Any], spatial: dict[str, Any]) -> dict[str, Any]:
        text = str(spatial.get("combined_text") or "")
        if not text.strip():
            return original_preview
        return {
            **original_preview,
            "mode": "spatial-text",
            "text": text,
            "truncated": bool(spatial.get("truncated")),
            "spatial_source": True,
        }

    @staticmethod
    def attach_fact_locations(dna: dict[str, Any], spatial: dict[str, Any]) -> None:
        line_map = {
            int(item.get("global_line")): item
            for item in spatial.get("line_map") or []
            if item.get("global_line")
        }
        located = 0
        for fact in dna.get("molecules", {}).get("facts", []):
            source = fact.setdefault("source", {})
            line = int(source.get("line") or 0)
            location = line_map.get(line)
            if not location:
                continue
            source["locator"] = {
                "page": location.get("page"),
                "line_id": location.get("line_id"),
                "line": line,
                "bbox": location.get("bbox"),
                "extraction_method": location.get("extraction_method"),
                "coordinate_status": "exact_from_document_engine",
            }
            located += 1

        total = len(dna.get("molecules", {}).get("facts", []))
        dna["spatial_evidence"] = {
            "located_facts": located,
            "total_facts": total,
            "coverage_percent": round(located / max(1, total) * 100, 2),
        }

        document_quality = dna.setdefault("document_quality", {})
        document_quality["spatial_score"] = spatial.get("quality", {}).get("score", 0)
        document_quality["spatial_pages"] = spatial.get("page_count", 0)
        document_quality["ocr_pages"] = spatial.get("ocr", {}).get("used_pages", 0)
        document_quality["spatial_engine_version"] = SPATIAL_ENGINE_VERSION

        for chain in dna.get("evidence_chains") or []:
            evidence_items = []
            for evidence in chain.get("evidence") or []:
                if not isinstance(evidence, dict):
                    evidence_items.append(evidence)
                    continue
                copied = dict(evidence)
                line = int(copied.get("line") or 0)
                if line in line_map:
                    copied["locator"] = {
                        "page": line_map[line].get("page"),
                        "bbox": line_map[line].get("bbox"),
                        "line_id": line_map[line].get("line_id"),
                    }
                evidence_items.append(copied)
            chain["evidence"] = evidence_items

        ai_context = dna.get("ai_context")
        if isinstance(ai_context, dict):
            fact_lookup = {
                str(fact.get("id")): fact
                for fact in dna.get("molecules", {}).get("facts", [])
                if fact.get("id")
            }
            for item in ai_context.get("facts") or []:
                fact = fact_lookup.get(str(item.get("fact_id")))
                if fact:
                    locator = (fact.get("source") or {}).get("locator")
                    if locator:
                        item.setdefault("source", {})["locator"] = locator

    @staticmethod
    def compact_summary(spatial: dict[str, Any]) -> dict[str, Any]:
        capabilities = spatial.get("capabilities") or {}
        return {
            "engine_version": spatial.get("engine_version"),
            "status": spatial.get("status"),
            "reason": spatial.get("reason"),
            "page_count": spatial.get("page_count", 0),
            "source_page_count": spatial.get("source_page_count", 0),
            "truncated": bool(spatial.get("truncated")),
            "force_ocr": bool(spatial.get("force_ocr")),
            "ocr": spatial.get("ocr", {}),
            "tables": spatial.get("tables", {}),
            "visual_candidates": spatial.get("visual_candidates", {}),
            "quality": spatial.get("quality", {}),
            "spatial_sha256": spatial.get("spatial_sha256"),
            "capabilities": {
                "pdfium_available": capabilities.get("pdfium_available"),
                "pdfium_version": capabilities.get("pdfium_version"),
                "pillow_available": capabilities.get("pillow_available"),
                "pillow_version": capabilities.get("pillow_version"),
                "tesseract_available": capabilities.get("tesseract_available"),
                "ocr_ready": capabilities.get("ocr_ready"),
                "ocr_languages": capabilities.get("ocr_languages", []),
            },
        }
