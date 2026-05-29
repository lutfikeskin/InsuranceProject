import json

import pytest

from modules.coi.holders import (
    COIHolderError,
    append_coi_holder,
    build_full_address,
    export_coi_holders_bytes,
    load_coi_holders,
    merge_coi_holders_from_bytes,
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
                    "email": "certs@alpha.example",
                }
            ]
        ),
        encoding="utf-8",
    )
    loaded = load_coi_holders(path)
    assert loaded["Alpha LLC"]["city"] == "Dallas"
    assert loaded["Alpha LLC"]["zip"] == "75001"
    assert loaded["Alpha LLC"]["email"] == "certs@alpha.example"


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
    assert loaded["Beta Transport"]["email"] == "ops@beta.com"


def test_append_rejects_empty_name(tmp_path):
    path = tmp_path / "holders.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(COIHolderError, match="required"):
        append_coi_holder(path, name="   ")


def test_export_coi_holders_bytes(tmp_path):
    path = tmp_path / "holders.json"
    path.write_text('[{"name": "Export Co"}]', encoding="utf-8")
    payload = export_coi_holders_bytes(path)
    assert b"Export Co" in payload


def test_merge_coi_holders_from_bytes(tmp_path):
    path = tmp_path / "holders.json"
    path.write_text(
        json.dumps(
            [{"name": "Existing Co", "address": "1 St", "city": "A", "state": "TX", "zip": "1"}]
        ),
        encoding="utf-8",
    )
    incoming = json.dumps(
        [
            {"name": "Existing Co", "address": "x"},
            {"name": "New Co", "address": "2 St", "city": "B", "state": "GA", "zip": "2"},
        ]
    ).encode("utf-8")

    result = merge_coi_holders_from_bytes(incoming, path)
    assert result.imported == 1
    assert result.skipped_duplicates == 1
    loaded = load_coi_holders(path)
    assert "New Co" in loaded
    assert len(json.loads(path.read_text(encoding="utf-8"))) == 2


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
