"""Connections-management dashboard API -- full CRUD over connections.yaml plus a
connectivity test endpoint. Mounted into openapi_server.py under /api/connections.

Every write goes through config.save_config(), which re-validates the whole
config (including the no-plaintext-secrets check) before touching disk -- the
same guarantee load_config() gives an LLM caller applies here to a human
editing through this UI. No route here ever accepts or returns a resolved
secret value; auth_method-specific credentials are still set out-of-band via
env var / keyring, exactly as documented in README.md's auth_method sections.
Every route reloads the config fresh (matches runtime.py's stateless
everything-reloads convention) rather than caching it in memory, so edits
made by hand to connections.yaml are picked up immediately.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from .client import EPMClient
from .config import AuthMethod, ConnectionConfig, OAuth2Config, load_config, save_config
from .endpoints import applications as ep_applications
from .exceptions import EPMToolkitError
from .runtime import config_path

router = APIRouter(prefix="/api/connections", tags=["dashboard"])


class ConnectionWrite(BaseModel):
    display_name: str
    base_url: str
    auth_method: AuthMethod = "basic"
    credential_ref: str
    default_application: str | None = None
    oauth2: OAuth2Config | None = None


class TestResult(BaseModel):
    success: bool
    message: str
    application_count: int | None = None
    latency_ms: float


@router.get("", response_model=list[ConnectionConfig])
async def list_connections() -> list[ConnectionConfig]:
    cfg = load_config(config_path())
    return list(cfg.connections.values())


@router.get("/{slug}", response_model=ConnectionConfig)
async def get_connection(slug: str) -> ConnectionConfig:
    cfg = load_config(config_path())
    if slug not in cfg.connections:
        raise HTTPException(status_code=404, detail=f"No connection named '{slug}'")
    return cfg.connections[slug]


def _build_connection(slug: str, body: ConnectionWrite) -> ConnectionConfig:
    """Construct a ConnectionConfig from a dashboard write, surfacing schema
    violations (e.g. auth_method=oauth2 with no oauth2: block) as a 400
    instead of an unhandled pydantic ValidationError.
    """
    try:
        return ConnectionConfig(slug=slug, **body.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{slug}", response_model=ConnectionConfig, status_code=201)
async def create_connection(slug: str, body: ConnectionWrite) -> ConnectionConfig:
    cfg = load_config(config_path())
    if slug in cfg.connections:
        raise HTTPException(status_code=409, detail=f"Connection '{slug}' already exists")
    conn = _build_connection(slug, body)
    cfg.connections[slug] = conn
    save_config(cfg, config_path())
    return conn


@router.put("/{slug}", response_model=ConnectionConfig)
async def update_connection(slug: str, body: ConnectionWrite) -> ConnectionConfig:
    cfg = load_config(config_path())
    if slug not in cfg.connections:
        raise HTTPException(status_code=404, detail=f"No connection named '{slug}'")
    conn = _build_connection(slug, body)
    cfg.connections[slug] = conn
    save_config(cfg, config_path())
    return conn


@router.delete("/{slug}", status_code=204)
async def delete_connection(slug: str) -> None:
    cfg = load_config(config_path())
    if slug not in cfg.connections:
        raise HTTPException(status_code=404, detail=f"No connection named '{slug}'")
    del cfg.connections[slug]
    save_config(cfg, config_path())


@router.post("/{slug}/test", response_model=TestResult)
async def test_connection(slug: str) -> TestResult:
    """Lightweight connectivity check: list_applications, since it's valid
    for every auth_method and needs no application name up front. Never
    raises -- auth/connectivity failures come back as success=False with the
    library's own redacted error message (never a raw secret; see
    client.py/config.py's redaction guarantees), not a 500.
    """
    cfg = load_config(config_path())
    if slug not in cfg.connections:
        raise HTTPException(status_code=404, detail=f"No connection named '{slug}'")
    conn = cfg.connections[slug]

    client = EPMClient(conn)
    start = time.monotonic()
    try:
        apps = await ep_applications.list_applications(client)
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        return TestResult(
            success=True,
            message=f"Connected -- {len(apps)} application(s) visible.",
            application_count=len(apps),
            latency_ms=elapsed_ms,
        )
    except EPMToolkitError as exc:
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        return TestResult(success=False, message=str(exc), latency_ms=elapsed_ms)
    except Exception as exc:  # noqa: BLE001 -- surface as a failed test, not a 500
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        return TestResult(success=False, message=f"{type(exc).__name__}: {exc}", latency_ms=elapsed_ms)
    finally:
        await client.aclose()
