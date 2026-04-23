"""Core image-processing logic for LINE sticker tool."""

from __future__ import annotations

import io
import json
import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

# ---------------------------------------------------------------------------
# LINE sticker size constants
# ---------------------------------------------------------------------------
STICKER_MAX_W: int = 370
STICKER_MAX_H: int = 320
MAIN_SIZE: tuple[int, int] = (240, 240)
TAB_SIZE: tuple[int, int] = (96, 74)
VALID_COUNTS: tuple[int, ...] = (8, 16, 24, 32, 40)
PADDING: int = 10          # px margin around content on all sides
MAX_IMAGE_BYTES: int = 1_000_000   # 1 MB per image
MAX_ZIP_BYTES: int = 60_000_000    # 60 MB total zip


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class ValidationResult:
    """Per-image validation outcome."""
    filename: str
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.ok = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def as_dict(self) -> dict:
        return {
            "filename": self.filename,
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
        }


@dataclass
class ProcessingOptions:
    """Options passed to StickerProcessor."""
    count: int = 16
    use_rembg: bool = True
    main_path: Optional[Path] = None
    tab_path: Optional[Path] = None


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def ensure_even(value: int) -> int:
    """Return *value* rounded down to the nearest even integer."""
    return value if value % 2 == 0 else value - 1


def content_bbox(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Return the bounding box of non-transparent pixels, or None if all transparent."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    alpha = img.split()[3]
    bbox = alpha.getbbox()
    return bbox  # (left, upper, right, lower) or None


def crop_to_content(img: Image.Image) -> Image.Image:
    """Crop image to its non-transparent content bounding box."""
    bbox = content_bbox(img)
    if bbox is None:
        return img  # fully transparent – return as-is
    return img.crop(bbox)


def fit_with_padding(
    img: Image.Image,
    canvas_w: int,
    canvas_h: int,
    padding: int = PADDING,
    even_dims: bool = False,
) -> Image.Image:
    """
    Fit *img* (cropped to content) into *canvas_w* × *canvas_h* with
    *padding* px margin on all sides, centered on a transparent canvas.

    If *even_dims* is True the output canvas dimensions are forced to
    even numbers before sizing (useful for sticker images).
    """
    if even_dims:
        canvas_w = ensure_even(canvas_w)
        canvas_h = ensure_even(canvas_h)

    available_w = canvas_w - 2 * padding
    available_h = canvas_h - 2 * padding
    available_w = max(available_w, 1)
    available_h = max(available_h, 1)

    # Ensure img has an alpha channel
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    # Scale content to fit within available area, preserving aspect ratio
    img.thumbnail((available_w, available_h), Image.LANCZOS)

    # Center on transparent canvas
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    paste_x = (canvas_w - img.width) // 2
    paste_y = (canvas_h - img.height) // 2
    canvas.paste(img, (paste_x, paste_y), img)
    return canvas


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_image(img_bytes: bytes, filename: str) -> ValidationResult:
    """Run LINE-spec validation on raw PNG bytes."""
    result = ValidationResult(filename=filename)

    # Size check
    if len(img_bytes) > MAX_IMAGE_BYTES:
        result.add_error(
            f"File size {len(img_bytes):,} bytes exceeds 1 MB limit."
        )

    try:
        img = Image.open(io.BytesIO(img_bytes))
    except Exception as exc:
        result.add_error(f"Cannot open image: {exc}")
        return result

    # Format
    if img.format and img.format != "PNG":
        result.add_warning(f"Image format is {img.format!r}; PNG is required.")

    # Mode / alpha
    if img.mode != "RGBA":
        result.add_warning(
            f"Image mode is {img.mode!r}; RGBA (transparent PNG) is recommended."
        )

    # DPI
    dpi = img.info.get("dpi")
    if dpi is None:
        result.add_warning("No DPI metadata found; ≥72 dpi is recommended.")
    else:
        min_dpi = min(dpi) if hasattr(dpi, "__iter__") else dpi
        if min_dpi < 72:
            result.add_warning(f"DPI is {min_dpi}; ≥72 dpi is required.")

    # Heuristic: extreme aspect ratio
    w, h = img.size
    if w > 0 and h > 0:
        ratio = max(w, h) / min(w, h)
        if ratio > 4:
            result.add_warning(
                f"Extreme aspect ratio ({w}×{h}). Sticker may be hard to recognise."
            )

    # Heuristic: overly light image (may be invisible in chat)
    if img.mode in ("RGBA", "RGB", "L"):
        grey = img.convert("L")
        pixels = grey.tobytes()
        mean_brightness = sum(pixels) / len(pixels)
        if mean_brightness > 230:
            result.add_warning(
                f"Mean brightness {mean_brightness:.0f}/255 is very high; "
                "sticker may be hard to see on white background."
            )

    return result


# ---------------------------------------------------------------------------
# Optional background removal
# ---------------------------------------------------------------------------

def try_remove_background(img: Image.Image) -> Image.Image:
    """
    Attempt to remove the background with *rembg* if available.
    Returns the original image untouched when rembg is not installed.
    """
    try:
        from rembg import remove  # type: ignore[import]

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        result_bytes = remove(buf.getvalue())
        return Image.open(io.BytesIO(result_bytes)).convert("RGBA")
    except ImportError:
        return img
    except Exception:
        return img


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

ACCEPTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def load_image_as_rgba(path: Path) -> Image.Image:
    """Open any supported image and return it as RGBA."""
    img = Image.open(path)
    return img.convert("RGBA")


def collect_input_images(folder: Path) -> list[Path]:
    """Return sorted list of image paths inside *folder*."""
    paths: list[Path] = []
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.suffix.lower() in ACCEPTED_SUFFIXES:
            paths.append(p)
    return paths


def image_to_png_bytes(img: Image.Image, optimize: bool = True) -> bytes:
    """Encode *img* to PNG bytes, optionally applying size optimizations."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=optimize)
    data = buf.getvalue()

    # If still over 1 MB, try quantisation (for non-photographic content)
    if len(data) > MAX_IMAGE_BYTES:
        try:
            quantised = img.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
            quantised = quantised.convert("RGBA")
            buf2 = io.BytesIO()
            quantised.save(buf2, format="PNG", optimize=True)
            candidate = buf2.getvalue()
            if len(candidate) < len(data):
                data = candidate
        except Exception:
            pass

    return data


# ---------------------------------------------------------------------------
# Main processor
# ---------------------------------------------------------------------------

class StickerProcessor:
    """Orchestrates the full sticker-processing pipeline."""

    def __init__(self, options: Optional[ProcessingOptions] = None) -> None:
        self.opts = options or ProcessingOptions()
        if self.opts.count not in VALID_COUNTS:
            raise ValueError(
                f"count must be one of {VALID_COUNTS}, got {self.opts.count}"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_folder(
        self,
        input_folder: Path,
        output_zip: Path,
    ) -> list[ValidationResult]:
        """
        Process all images in *input_folder* and write a LINE-ready ZIP
        to *output_zip*. Returns a list of validation results.
        """
        images = collect_input_images(input_folder)
        if not images:
            raise FileNotFoundError(
                f"No supported images found in {input_folder}"
            )

        validations: list[ValidationResult] = []
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # --- main image ---
            main_src = self.opts.main_path or images[0]
            main_img = self._prepare_image(main_src)
            main_canvas = fit_with_padding(main_img, *MAIN_SIZE, even_dims=False)
            main_bytes = image_to_png_bytes(main_canvas)
            val = validate_image(main_bytes, "main.png")
            validations.append(val)
            zf.writestr("main.png", main_bytes)

            # --- tab image ---
            tab_src = self.opts.tab_path or images[0]
            tab_img = self._prepare_image(tab_src)
            tab_canvas = fit_with_padding(tab_img, *TAB_SIZE, even_dims=False)
            tab_bytes = image_to_png_bytes(tab_canvas)
            val = validate_image(tab_bytes, "tab.png")
            validations.append(val)
            zf.writestr("tab.png", tab_bytes)

            # --- sticker images ---
            count = self.opts.count
            # Cycle through available images to fill requested count
            for i in range(count):
                src = images[i % len(images)]
                sticker_img = self._prepare_image(src)
                sticker_canvas = fit_with_padding(
                    sticker_img,
                    STICKER_MAX_W,
                    STICKER_MAX_H,
                    even_dims=True,
                )
                sticker_bytes = image_to_png_bytes(sticker_canvas)
                name = f"{i + 1:02d}.png"
                val = validate_image(sticker_bytes, name)
                validations.append(val)
                zf.writestr(name, sticker_bytes)

        zip_data = zip_buffer.getvalue()

        # Total ZIP size check
        if len(zip_data) > MAX_ZIP_BYTES:
            for v in validations:
                v.add_warning(
                    f"Total ZIP size {len(zip_data):,} bytes exceeds 60 MB limit."
                )

        output_zip.parent.mkdir(parents=True, exist_ok=True)
        output_zip.write_bytes(zip_data)

        return validations

    def process_files(
        self,
        file_data: list[tuple[str, bytes]],
        count: int = 16,
    ) -> tuple[bytes, list[ValidationResult]]:
        """
        Process a list of (filename, raw_bytes) pairs and return
        (zip_bytes, validations). Used by the web interface.
        """
        if count not in VALID_COUNTS:
            raise ValueError(f"count must be one of {VALID_COUNTS}")

        images_rgba: list[Image.Image] = []
        for _name, raw in file_data:
            img = Image.open(io.BytesIO(raw)).convert("RGBA")
            images_rgba.append(img)

        if not images_rgba:
            raise ValueError("No images provided")

        validations: list[ValidationResult] = []
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # main
            main_img = self._prepare_rgba(images_rgba[0])
            main_canvas = fit_with_padding(main_img, *MAIN_SIZE)
            main_bytes = image_to_png_bytes(main_canvas)
            validations.append(validate_image(main_bytes, "main.png"))
            zf.writestr("main.png", main_bytes)

            # tab
            tab_img = self._prepare_rgba(images_rgba[0])
            tab_canvas = fit_with_padding(tab_img, *TAB_SIZE)
            tab_bytes = image_to_png_bytes(tab_canvas)
            validations.append(validate_image(tab_bytes, "tab.png"))
            zf.writestr("tab.png", tab_bytes)

            # stickers
            for i in range(count):
                src = images_rgba[i % len(images_rgba)]
                sticker_img = self._prepare_rgba(src)
                sticker_canvas = fit_with_padding(
                    sticker_img, STICKER_MAX_W, STICKER_MAX_H, even_dims=True
                )
                sticker_bytes = image_to_png_bytes(sticker_canvas)
                name = f"{i + 1:02d}.png"
                validations.append(validate_image(sticker_bytes, name))
                zf.writestr(name, sticker_bytes)

        return zip_buffer.getvalue(), validations

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _prepare_image(self, path: Path) -> Image.Image:
        img = load_image_as_rgba(path)
        return self._prepare_rgba(img)

    def _prepare_rgba(self, img: Image.Image) -> Image.Image:
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        if self.opts.use_rembg:
            img = try_remove_background(img)
        img = crop_to_content(img)
        return img

    def build_report(self, validations: list[ValidationResult]) -> str:
        """Return a JSON string summarising all validation results."""
        data = {
            "total": len(validations),
            "passed": sum(1 for v in validations if v.ok),
            "failed": sum(1 for v in validations if not v.ok),
            "results": [v.as_dict() for v in validations],
        }
        return json.dumps(data, ensure_ascii=False, indent=2)
