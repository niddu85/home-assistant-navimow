"""Fixtures for live tests against the real Navimow cloud.

These tests need tokens created by scripts/live_login.py and are skipped
otherwise. They run without the Home Assistant pytest plugin, which blocks
network access:

    pytest -p no:homeassistant -s tests_live
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiohttp
import pytest

from custom_components.navimow.api import NavimowApiClient
from custom_components.navimow.const import (
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
)

ROOT = Path(__file__).resolve().parents[1]
LIVE_DIR = ROOT / ".navimow_live"
TOKEN_FILE = LIVE_DIR / "tokens.json"
CAPTURE_DIR = LIVE_DIR / "captured"
SECRET_KEYS = {"access_token", "refresh_token", "pwdInfo"}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if TOKEN_FILE.exists():
        return
    skip = pytest.mark.skip(reason="no live tokens: run scripts/live_login.py first")
    for item in items:
        item.add_marker(skip)


def _redact(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: "**REDACTED**" if k in SECRET_KEYS else _redact(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_redact(v) for v in data]
    return data


def capture(name: str, data: Any) -> None:
    """Save a real API response (secrets redacted) for inspection."""
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    (CAPTURE_DIR / f"{name}.json").write_text(json.dumps(_redact(data), indent=2))


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as session:
        yield session


@pytest.fixture
def api(session: aiohttp.ClientSession) -> NavimowApiClient:
    """API client whose refreshed tokens are written back to the token file."""
    tokens = json.loads(TOKEN_FILE.read_text())

    def save_tokens(update: dict[str, Any]) -> None:
        tokens.update(update)
        TOKEN_FILE.write_text(json.dumps(tokens, indent=2))

    return NavimowApiClient(
        session,
        tokens[CONF_ACCESS_TOKEN],
        tokens[CONF_REFRESH_TOKEN],
        tokens[CONF_EXPIRES_AT],
        save_tokens,
    )
