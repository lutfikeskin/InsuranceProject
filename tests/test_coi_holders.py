import json

import pytest

from modules.coi.holders import (
    COIHolderError,
    append_coi_holder,
    build_full_address,
    load_coi_holders,
)


def test_build_full_address():
    assert build_full_address("1 Main St", "Austin", "TX", "78701") == (
        "1 Main St\nAustin, TX 78701"
    )
    assert build_full_address("1 Main St", "", "", "") == "1 Main St"


def test_load_coi_holders_empty_file(tmp_path):
    path = tmp_path / "holders.json"
    path.write_text("[]", encoding="utf-8")
    assert load_coi_holders(path) == {}


def test_load_coi_holders_parses_records(tmp_path):
    path = tmp_path / "holders.json"
    path.write_text(
        json.dumps(
            [
                {
                    "name": "Alpha LLC",
                    "address": "10 Road",
                    "city": "Dallas",
                    "state": "TX",
                    "zip": "75001",
                }
            ]
        ),
        encoding="utf-8",
    )
    loaded = load_coi_holders(path)
    assert loaded["Alpha LLC"]["city"] == "Dallas"
    assert loaded["Alpha LLC"]["zip"] == "75001"


def test_append_coi_holder_persists_record(tmp_path):
    path = tmp_path / "holders.json"
    path.write_text("[]", encoding="utf-8")

    saved = append_coi_holder(
        path,
        name="Beta Transport",
        address="20 Lane",
        city="Houston",
        state="TX",
        zip_code="77002",
        email="ops@beta.com",
    )

    assert saved["name"] == "Beta Transport"
    records = json.loads(path.read_text(encoding="utf-8"))
    assert len(records) == 1
    assert records[0]["email"] == "ops@beta.com"
    assert records[0]["full_address"] == "20 Lane\nHouston, TX 77002"

    loaded = load_coi_holders(path)
    assert "Beta Transport" in loaded


def test_append_rejects_empty_name(tmp_path):
    path = tmp_path / "holders.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(COIHolderError, match="required"):
        append_coi_holder(path, name="   ")


def test_append_rejects_duplicate_name_case_insensitive(tmp_path):
    path = tmp_path / "holders.json"
    path.write_text(
        json.dumps([{"name": "Gamma Inc", "address": "", "city": "", "state": "", "zip": ""}]),
        encoding="utf-8",
    )
    append_coi_holder(path, name="Other", address="1 St")
    with pytest.raises(COIHolderError, match="already exists"):
        append_coi_holder(path, name="gamma inc", address="2 St")

    records = json.loads(path.read_text(encoding="utf-8"))
    assert len(records) == 2
