"""Pytest tests for the FastAPI web application."""

from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from web.app import app

client = TestClient(app)


def _png_bytes(w: int = 100, h: int = 100) -> bytes:
    img = Image.new("RGBA", (w, h), (100, 150, 200, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestIndex:
    def test_get_returns_html(self):
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "LINE" in response.text


class TestHealth:
    def test_health_ok(self):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestProcess:
    def test_process_returns_zip(self):
        data = _png_bytes()
        response = client.post(
            "/process",
            data={"count": "8"},
            files=[("files", ("test.png", data, "image/png"))],
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            names = zf.namelist()
        assert "main.png" in names
        assert "tab.png" in names
        assert sum(1 for n in names if n not in ("main.png", "tab.png")) == 8

    def test_invalid_count_returns_422(self):
        data = _png_bytes()
        response = client.post(
            "/process",
            data={"count": "7"},
            files=[("files", ("test.png", data, "image/png"))],
        )
        assert response.status_code == 422

    def test_multiple_images(self):
        response = client.post(
            "/process",
            data={"count": "16"},
            files=[
                ("files", ("a.png", _png_bytes(80, 80), "image/png")),
                ("files", ("b.png", _png_bytes(120, 60), "image/png")),
            ],
        )
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            sticker_names = [n for n in zf.namelist() if n not in ("main.png", "tab.png")]
        assert len(sticker_names) == 16
