"""FastAPI web application for LINE sticker processing."""

from __future__ import annotations

import io
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse

from line_sticker_tool.core import VALID_COUNTS, StickerProcessor

app = FastAPI(
    title="LINE Sticker Tool",
    description="Upload images and receive a ready-to-submit LINE sticker ZIP.",
    version="0.1.0",
)

# ---------------------------------------------------------------------------
# HTML upload page
# ---------------------------------------------------------------------------
_UPLOAD_PAGE = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>LINE 貼圖裁切工具</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: Arial, sans-serif; max-width: 720px; margin: 40px auto; padding: 0 16px; background: #f8f9fa; color: #333; }
    h1 { color: #06c755; }
    label { display: block; margin: 12px 0 4px; font-weight: bold; }
    input[type=file], select { width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px; }
    button { margin-top: 20px; padding: 12px 28px; background: #06c755; color: #fff; border: none; border-radius: 4px; font-size: 16px; cursor: pointer; }
    button:hover { background: #059a42; }
    .hint { font-size: 13px; color: #666; }
    .warning { background: #fff3cd; border: 1px solid #ffc107; border-radius: 4px; padding: 10px; margin-top: 16px; }
  </style>
</head>
<body>
  <h1>🟢 LINE 貼圖裁切打包工具</h1>
  <p>上傳圖片後自動裁切、加白邊、校驗規格，並產生 LINE Creator Market 所需的 ZIP 包。</p>

  <div class="warning">
    ⚠️ 請確認圖片已去背（透明背景 PNG）以獲得最佳效果。
  </div>

  <form method="post" action="/process" enctype="multipart/form-data">
    <label for="files">選擇圖片（PNG / JPG，可多選）</label>
    <input type="file" id="files" name="files" multiple accept="image/*" required />
    <span class="hint">至少上傳 1 張，超過貼圖數量時會循環使用</span>

    <label for="count">貼圖張數</label>
    <select id="count" name="count">
      <option value="8">8 張</option>
      <option value="16" selected>16 張（預設）</option>
      <option value="24">24 張</option>
      <option value="32">32 張</option>
      <option value="40">40 張</option>
    </select>

    <button type="submit">⬇️ 立即處理並下載 ZIP</button>
  </form>

  <hr style="margin-top:40px"/>
  <h2>API 說明</h2>
  <ul>
    <li><code>GET /</code> – 本頁面（上傳介面）</li>
    <li><code>POST /process</code> – 接收圖片 + count，回傳 ZIP</li>
    <li><code>GET /health</code> – 健康檢查</li>
  </ul>
  <p>詳細 API 文件請見 <a href="/docs">/docs</a>（Swagger UI）</p>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse, summary="Upload page")
async def index() -> HTMLResponse:
    """Return the HTML upload interface."""
    return HTMLResponse(content=_UPLOAD_PAGE)


@app.get("/health", summary="Health check")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/process", summary="Process stickers and return ZIP")
async def process(
    files: Annotated[list[UploadFile], File(description="Source images (PNG/JPG)")],
    count: Annotated[int, Form(description="Sticker count (8/16/24/32/40)")] = 16,
) -> StreamingResponse:
    """
    Accept multiple images and the desired sticker count, then return a ZIP
    file containing:
    - `main.png` (240×240)
    - `tab.png` (96×74)
    - `01.png` … `NN.png` (up to 370×320, even dimensions)
    """
    if count not in VALID_COUNTS:
        raise HTTPException(
            status_code=422,
            detail=f"count must be one of {list(VALID_COUNTS)}, got {count}",
        )

    if not files:
        raise HTTPException(status_code=422, detail="At least one image file is required.")

    file_data: list[tuple[str, bytes]] = []
    for upload in files:
        raw = await upload.read()
        if not raw:
            raise HTTPException(
                status_code=422,
                detail=f"Uploaded file '{upload.filename}' is empty.",
            )
        file_data.append((upload.filename or "unknown", raw))

    try:
        processor = StickerProcessor()
        zip_bytes, validations = processor.process_files(file_data, count=count)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Processing error: {exc}") from exc

    # Build a summary of validation issues for the response headers
    errors = [
        f"{v.filename}: {'; '.join(v.errors)}"
        for v in validations
        if v.errors
    ]
    warnings = [
        f"{v.filename}: {'; '.join(v.warnings)}"
        for v in validations
        if v.warnings
    ]

    def _ascii_safe(text: str, max_len: int = 500) -> str:
        """Strip non-ASCII characters so HTTP headers stay latin-1 safe."""
        return text.encode("ascii", errors="replace").decode("ascii")[:max_len]

    headers: dict[str, str] = {
        "Content-Disposition": 'attachment; filename="stickers.zip"',
    }
    if errors:
        headers["X-Validation-Errors"] = _ascii_safe(" | ".join(errors))
    if warnings:
        headers["X-Validation-Warnings"] = _ascii_safe(" | ".join(warnings))

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Run directly
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("web.app:app", host="0.0.0.0", port=8000, reload=True)
