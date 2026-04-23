"""Pytest tests for core geometry and validation logic."""

from __future__ import annotations

import io
import zipfile

import pytest
from PIL import Image

from line_sticker_tool.core import (
    STICKER_MAX_H,
    STICKER_MAX_W,
    VALID_COUNTS,
    content_bbox,
    crop_to_content,
    ensure_even,
    fit_with_padding,
    validate_image,
    image_to_png_bytes,
    StickerProcessor,
    ProcessingOptions,
)


# ---------------------------------------------------------------------------
# ensure_even
# ---------------------------------------------------------------------------

class TestEnsureEven:
    def test_even_unchanged(self):
        assert ensure_even(10) == 10

    def test_odd_decremented(self):
        assert ensure_even(11) == 10

    def test_zero(self):
        assert ensure_even(0) == 0

    def test_one(self):
        assert ensure_even(1) == 0

    def test_large_even(self):
        assert ensure_even(370) == 370

    def test_large_odd(self):
        assert ensure_even(371) == 370


# ---------------------------------------------------------------------------
# content_bbox / crop_to_content
# ---------------------------------------------------------------------------

def _make_rgba(width: int, height: int, content_rect: tuple[int, int, int, int] | None = None) -> Image.Image:
    """Create a transparent RGBA image, optionally drawing an opaque rectangle."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if content_rect is not None:
        x0, y0, x1, y1 = content_rect
        for x in range(x0, x1):
            for y in range(y0, y1):
                img.putpixel((x, y), (255, 0, 0, 255))
    return img


class TestContentBbox:
    def test_fully_transparent_returns_none(self):
        img = _make_rgba(100, 100)
        assert content_bbox(img) is None

    def test_single_pixel(self):
        img = _make_rgba(50, 50)
        img.putpixel((10, 20), (0, 0, 0, 255))
        bbox = content_bbox(img)
        assert bbox == (10, 20, 11, 21)

    def test_content_rect(self):
        img = _make_rgba(200, 200, (20, 30, 80, 90))
        bbox = content_bbox(img)
        assert bbox == (20, 30, 80, 90)

    def test_rgb_image_converted(self):
        img = Image.new("RGB", (100, 100), (255, 0, 0))
        bbox = content_bbox(img)
        # All pixels are opaque after RGBA conversion
        assert bbox == (0, 0, 100, 100)


class TestCropToContent:
    def test_crop_removes_transparent_border(self):
        img = _make_rgba(200, 200, (50, 60, 100, 120))
        cropped = crop_to_content(img)
        assert cropped.size == (50, 60)

    def test_fully_transparent_unchanged(self):
        img = _make_rgba(100, 100)
        result = crop_to_content(img)
        assert result.size == (100, 100)


# ---------------------------------------------------------------------------
# fit_with_padding
# ---------------------------------------------------------------------------

class TestFitWithPadding:
    def test_output_size_matches_canvas(self):
        img = _make_rgba(50, 50, (0, 0, 50, 50))
        result = fit_with_padding(img, 240, 240)
        assert result.size == (240, 240)

    def test_sticker_canvas_even_dims(self):
        img = _make_rgba(100, 100, (0, 0, 100, 100))
        result = fit_with_padding(img, STICKER_MAX_W, STICKER_MAX_H, even_dims=True)
        w, h = result.size
        assert w % 2 == 0, f"Width {w} is not even"
        assert h % 2 == 0, f"Height {h} is not even"

    def test_content_centered_with_padding(self):
        # Content should not touch the edges
        img = _make_rgba(100, 100, (0, 0, 100, 100))
        canvas_w, canvas_h = 240, 240
        result = fit_with_padding(img, canvas_w, canvas_h, padding=10)
        assert result.size == (canvas_w, canvas_h)
        # The alpha channel border should be transparent (padding)
        alpha = result.split()[3]
        # Top-left corner should be transparent
        assert alpha.getpixel((0, 0)) == 0
        assert alpha.getpixel((canvas_w - 1, 0)) == 0

    def test_odd_canvas_forced_even(self):
        img = _make_rgba(50, 50, (0, 0, 50, 50))
        result = fit_with_padding(img, 371, 321, even_dims=True)
        w, h = result.size
        assert w == 370
        assert h == 320

    def test_output_is_rgba(self):
        img = _make_rgba(80, 80, (10, 10, 70, 70))
        result = fit_with_padding(img, 370, 320)
        assert result.mode == "RGBA"


# ---------------------------------------------------------------------------
# validate_image
# ---------------------------------------------------------------------------

def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestValidateImage:
    def test_valid_rgba_png(self):
        img = Image.new("RGBA", (240, 240), (0, 0, 0, 0))
        data = _png_bytes(img)
        result = validate_image(data, "test.png")
        # Should have no errors (may have a dpi warning, which is acceptable)
        assert result.ok
        assert result.errors == []

    def test_oversized_image_raises_error(self):
        # Create a large image that will exceed 1 MB
        large_img = Image.new("RGBA", (2000, 2000), (128, 128, 128, 255))
        data = _png_bytes(large_img)
        if len(data) > 1_000_000:
            result = validate_image(data, "big.png")
            assert not result.ok
            assert any("1 MB" in e for e in result.errors)

    def test_non_rgba_warning(self):
        img = Image.new("RGB", (100, 100), (255, 255, 255))
        data = _png_bytes(img)
        result = validate_image(data, "rgb.png")
        assert any("RGBA" in w for w in result.warnings)

    def test_extreme_aspect_ratio_warning(self):
        img = Image.new("RGBA", (500, 50), (0, 0, 0, 128))
        data = _png_bytes(img)
        result = validate_image(data, "wide.png")
        assert any("aspect ratio" in w.lower() for w in result.warnings)

    def test_bright_image_warning(self):
        img = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
        data = _png_bytes(img)
        result = validate_image(data, "bright.png")
        assert any("brightness" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# StickerProcessor integration (in-memory)
# ---------------------------------------------------------------------------

def _build_file_data(n: int = 2) -> list[tuple[str, bytes]]:
    out = []
    for i in range(n):
        img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        # Draw a coloured square as content
        for x in range(40, 160):
            for y in range(40, 160):
                img.putpixel((x, y), (i * 80 % 255, 100, 200, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        out.append((f"img{i}.png", buf.getvalue()))
    return out


class TestStickerProcessor:
    @pytest.mark.parametrize("count", [8, 16])
    def test_process_files_returns_valid_zip(self, count: int):
        processor = StickerProcessor(ProcessingOptions(count=count, use_rembg=False))
        file_data = _build_file_data(2)
        zip_bytes, validations = processor.process_files(file_data, count=count)

        assert len(zip_bytes) > 0
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = set(zf.namelist())
        assert "main.png" in names
        assert "tab.png" in names
        assert len([n for n in names if n.endswith(".png") and n not in ("main.png", "tab.png")]) == count

    def test_sticker_images_have_even_dimensions(self):
        processor = StickerProcessor(ProcessingOptions(count=8, use_rembg=False))
        file_data = _build_file_data(1)
        zip_bytes, _ = processor.process_files(file_data, count=8)

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for name in zf.namelist():
                if name in ("main.png", "tab.png"):
                    continue
                img = Image.open(io.BytesIO(zf.read(name)))
                assert img.width % 2 == 0, f"{name}: width {img.width} is not even"
                assert img.height % 2 == 0, f"{name}: height {img.height} is not even"

    def test_main_image_size(self):
        processor = StickerProcessor(ProcessingOptions(count=8, use_rembg=False))
        file_data = _build_file_data(1)
        zip_bytes, _ = processor.process_files(file_data, count=8)

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            img = Image.open(io.BytesIO(zf.read("main.png")))
        assert img.size == (240, 240)

    def test_tab_image_size(self):
        processor = StickerProcessor(ProcessingOptions(count=8, use_rembg=False))
        file_data = _build_file_data(1)
        zip_bytes, _ = processor.process_files(file_data, count=8)

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            img = Image.open(io.BytesIO(zf.read("tab.png")))
        assert img.size == (96, 74)

    def test_sticker_images_within_max_bounds(self):
        processor = StickerProcessor(ProcessingOptions(count=8, use_rembg=False))
        file_data = _build_file_data(1)
        zip_bytes, _ = processor.process_files(file_data, count=8)

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for name in zf.namelist():
                if name in ("main.png", "tab.png"):
                    continue
                img = Image.open(io.BytesIO(zf.read(name)))
                assert img.width <= STICKER_MAX_W, f"{name} width {img.width} > {STICKER_MAX_W}"
                assert img.height <= STICKER_MAX_H, f"{name} height {img.height} > {STICKER_MAX_H}"

    def test_invalid_count_raises(self):
        with pytest.raises(ValueError):
            StickerProcessor(ProcessingOptions(count=7))

    def test_report_json(self):
        import json
        processor = StickerProcessor(ProcessingOptions(count=8, use_rembg=False))
        file_data = _build_file_data(1)
        _, validations = processor.process_files(file_data, count=8)
        report = processor.build_report(validations)
        data = json.loads(report)
        assert "total" in data
        assert "results" in data
        assert data["total"] == 8 + 2  # 8 stickers + main + tab
