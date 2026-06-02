"""
tests/test_security_headers.py — Cabeceras de seguridad en las respuestas.
"""
import pytest


@pytest.mark.asyncio
async def test_headers_de_seguridad_presentes(client):
    r = await client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"


@pytest.mark.asyncio
async def test_hsts_ausente_en_desarrollo(client):
    # HSTS solo se emite en producción; en tests el entorno es development.
    r = await client.get("/health")
    assert "strict-transport-security" not in r.headers
