"""
tests/test_token_revocacion.py — Blocklist persistida de refresh tokens.

Verifica que la revocación:
- Detecta correctamente tokens revocados vs no revocados.
- Guarda el SHA-256, nunca el token crudo.
- Es idempotente (revocar dos veces no rompe).
- Purga registros cuyo token ya expiró.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models.token_revocado import TokenRevocado
from app.routers.auth import (
    _hash_token,
    _refresh_token_revocado,
    _revocar_refresh_token,
    crear_refresh_token,
)


@pytest.mark.asyncio
async def test_token_no_revocado_inicialmente(db_session):
    token = crear_refresh_token(str(uuid.uuid4()))
    assert await _refresh_token_revocado(db_session, token) is False


@pytest.mark.asyncio
async def test_revocar_marca_token_como_revocado(db_session):
    token = crear_refresh_token(str(uuid.uuid4()))
    await _revocar_refresh_token(db_session, token)
    await db_session.flush()
    assert await _refresh_token_revocado(db_session, token) is True


@pytest.mark.asyncio
async def test_guarda_hash_no_token_crudo(db_session):
    token = crear_refresh_token(str(uuid.uuid4()))
    await _revocar_refresh_token(db_session, token)
    await db_session.flush()

    guardado = (await db_session.execute(select(TokenRevocado))).scalar_one()
    assert guardado.token_hash == _hash_token(token)
    assert guardado.token_hash != token  # nunca el token crudo
    assert len(guardado.token_hash) == 64  # sha256 hex


@pytest.mark.asyncio
async def test_revocar_es_idempotente(db_session):
    token = crear_refresh_token(str(uuid.uuid4()))
    await _revocar_refresh_token(db_session, token)
    await db_session.flush()
    await _revocar_refresh_token(db_session, token)
    await db_session.flush()

    total = (await db_session.execute(
        select(func.count(TokenRevocado.id)).where(
            TokenRevocado.token_hash == _hash_token(token)
        )
    )).scalar()
    assert total == 1


@pytest.mark.asyncio
async def test_purga_registros_expirados(db_session):
    # Registro vencido: su token ya expiró hace una hora.
    vencido = TokenRevocado(
        token_hash="a" * 64,
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1),
    )
    db_session.add(vencido)
    await db_session.flush()

    # Revocar un token válido dispara el housekeeping que purga los vencidos.
    token = crear_refresh_token(str(uuid.uuid4()))
    await _revocar_refresh_token(db_session, token)
    await db_session.flush()

    restantes = (await db_session.execute(
        select(TokenRevocado.token_hash)
    )).scalars().all()
    assert "a" * 64 not in restantes          # el vencido se purgó
    assert _hash_token(token) in restantes     # el nuevo sigue (no vencido)
