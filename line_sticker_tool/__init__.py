"""LINE Sticker Tool – core library."""

from .core import (
    StickerProcessor,
    ValidationResult,
    ProcessingOptions,
    VALID_COUNTS,
    STICKER_MAX_W,
    STICKER_MAX_H,
    MAIN_SIZE,
    TAB_SIZE,
)

__all__ = [
    "StickerProcessor",
    "ValidationResult",
    "ProcessingOptions",
    "VALID_COUNTS",
    "STICKER_MAX_W",
    "STICKER_MAX_H",
    "MAIN_SIZE",
    "TAB_SIZE",
]
