"""Load and persist certificate holder records in data/coi_holders.json."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_HOLDERS_PATH = Path("data/coi_holders.json")


class COIHolderError(ValueError):
    """Validation or persistence error for COI holder records."""


def build_full_address(
    address: str = "",
    city: str = "",
    state: str = "",
    zip_code: str = "",
) -> str:
    """Compose full_address to match existing coi_holders.json records."""
    address = (address or "").strip()
    city = (city or "").strip()
    state = (state or "").strip()
    zip_code = (zip_code or "").strip()

    lines: list[str] = []
    if address:
        lines.append(address)

    city_state_zip_parts = []
    if city:
        city_state_zip_parts.append(city)
    tail = " ".join(p for p in (state, zip_code) if p).strip()
    if tail:
        if city_state_zip_parts:
            lines.append(f"{city_state_zip_parts[0]}, {tail}")
        else:
            lines.append(tail)
    elif city_state_zip_parts:
        lines.append(city_state_zip_parts[0])

    return "\n".join(lines)


def _normalize_holder_record(raw: dict[str, Any]) -> dict[str, str]:
    name = str(raw.get("name", "")).strip()
    address = str(raw.get("address", "")).strip()
    city = str(raw.get("city", "")).strip()
    state = str(raw.get("state", "")).strip()
    zip_code = str(raw.get("zip", "")).strip()
    return {
        "name": name,
        "address": address,
        "city": city,
        "state": state,
        "zip": zip_code,
    }


def _read_holders_file(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise COIHolderError(f"Expected a JSON array in {path}")
    return data


def load_coi_holders(path: str | Path | None = None) -> dict[str, dict[str, str]]:
    """
    Read holder library and return dict keyed by company name (UI quick-fill shape).
    Later entries win when names duplicate case-insensitively.
    """
    holders_path = Path(path) if path is not None else DEFAULT_HOLDERS_PATH
    try:
        records = _read_holders_file(holders_path)
    except json.JSONDecodeError as exc:
        print(f"Error loading COI holders JSON: {exc}")
        return {}

    companies: dict[str, dict[str, str]] = {}
    seen_lower: dict[str, str] = {}

    for raw in records:
        if not isinstance(raw, dict):
            continue
        normalized = _normalize_holder_record(raw)
        name = normalized["name"]
        if not name:
            continue
        key_lower = name.casefold()
        if key_lower in seen_lower:
            del companies[seen_lower[key_lower]]
        seen_lower[key_lower] = name
        companies[name] = normalized

    return companies


def append_coi_holder(
    path: str | Path | None = None,
    *,
    name: str,
    address: str = "",
    city: str = "",
    state: str = "",
    zip_code: str = "",
    email: str = "",
) -> dict[str, str]:
    """Append a holder record after validation; returns the saved record dict."""
    holders_path = Path(path) if path is not None else DEFAULT_HOLDERS_PATH
    name = (name or "").strip()
    if not name:
        raise COIHolderError("Holder name is required.")

    address = (address or "").strip()
    city = (city or "").strip()
    state = (state or "").strip()
    zip_code = (zip_code or "").strip()
    email = (email or "").strip()

    records = _read_holders_file(holders_path)
    for raw in records:
        if not isinstance(raw, dict):
            continue
        existing_name = str(raw.get("name", "")).strip()
        if existing_name and existing_name.casefold() == name.casefold():
            raise COIHolderError(f"A holder named '{existing_name}' already exists.")

    record = {
        "name": name,
        "full_address": build_full_address(address, city, state, zip_code),
        "address": address,
        "city": city,
        "state": state,
        "zip": zip_code,
        "email": email,
    }
    records.append(record)

    holders_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        suffix=".json",
        dir=str(holders_path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            json.dump(records, tmp, indent=4, ensure_ascii=False)
            tmp.write("\n")
        os.replace(temp_path, holders_path)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise

    return _normalize_holder_record(record)
