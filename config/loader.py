"""
City config loader.

Single entry point for reading `config/cities/<slug>.json`. Loaded configs are
validated against a Pydantic schema so misspelled keys, missing required
fields, or wrong value types fail at load time with a clear field path,
instead of much later at use time.

The schema is permissive (`extra="allow"`) — new optional config keys do not
require schema changes. Downstream callers consume the result as a plain
dict for compatibility with existing `city_config[...]` access patterns.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, ValidationError

_CITIES_DIR = Path(__file__).parent / "cities"


class CityConfigNotFoundError(FileNotFoundError):
    """Raised when no config file matches the requested city slug."""


class CityConfigError(ValueError):
    """Raised when a city config file is structurally invalid."""


class _CouncilMember(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    title: str
    district: Optional[str] = None
    profile_url: Optional[str] = None
    phone: Optional[str] = None
    photo_filename: Optional[str] = None


class _Newsletter(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    tagline: Optional[str] = ""
    subscribe_url: Optional[str] = None
    photo_base_url: Optional[str] = ""


class _Llm(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str = "anthropic/claude-sonnet-4.6"


class _CivicClerk(BaseModel):
    model_config = ConfigDict(extra="allow")
    subdomain: str
    category_id: int


class CityConfig(BaseModel):
    """Schema for `config/cities/<slug>.json`.

    Forgiving by design: `extra="allow"` so config files can carry arbitrary
    extra keys without breaking the loader. The fields below are the ones the
    pipeline actively reads — required fields raise; everything else is
    optional with sensible defaults.
    """
    model_config = ConfigDict(extra="allow")

    name: str
    state: str
    newsletter: _Newsletter
    council_members: list[_CouncilMember] = []
    rss_feeds: dict[str, str] = {}
    llm: _Llm = _Llm()
    civicclerk: Optional[_CivicClerk] = None
    youtube_channel_handle: Optional[str] = None
    youtube_playlist_id: Optional[str] = None
    meeting_keywords: list[str] = []
    meeting_type_keywords: dict[str, list[str]] = {}
    meeting_purpose_blurbs: dict[str, str] = {}
    schedule_portal_url: Optional[str] = None
    timezone: Optional[str] = None


def load_city_config(city: str) -> dict:
    """Load `config/cities/<city>.json`, validate it, return as a dict.

    Raises `CityConfigNotFoundError` if the file does not exist (with a
    helpful list of available configs), or `CityConfigError` if the file
    exists but doesn't satisfy the schema.
    """
    path = _CITIES_DIR / f"{city}.json"
    if not path.exists():
        available = ", ".join(available_cities()) or "(none)"
        raise CityConfigNotFoundError(
            f"City config not found: {path}. Available: {available}"
        )
    raw = json.loads(path.read_text())
    try:
        validated = CityConfig.model_validate(raw)
    except ValidationError as e:
        raise CityConfigError(f"Invalid city config {path}:\n{e}") from e
    # Return as dict to preserve compatibility with existing `cfg[...]` access.
    return validated.model_dump(mode="json")


def available_cities() -> list[str]:
    """Return the stems of every config/cities/*.json file."""
    return sorted(p.stem for p in _CITIES_DIR.glob("*.json"))
