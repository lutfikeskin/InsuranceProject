from types import SimpleNamespace

import utils.vehicle_utils as vehicle_utils
from core.services import _format_coi_vehicle_label
from views.create_coi import _format_vehicle_for_description


def test_coi_vehicle_label_includes_stored_model():
    vehicle = SimpleNamespace(year=2019, make="FORD", model="TRANSIT", vin="VIN123")

    assert _format_coi_vehicle_label(vehicle) == "[2019 FORD Transit VIN123]"


def test_coi_vehicle_label_decodes_missing_model(monkeypatch):
    vehicle = SimpleNamespace(year=2020, make="MERCEDES-BENZ", model=None, vin="WD4PF0CD0KP000000")

    monkeypatch.setattr(vehicle_utils, "decode_vin_nhtsa", lambda vin: {"Model": "SPRINTER"})

    assert _format_coi_vehicle_label(vehicle) == "[2020 MERCEDES-BENZ Sprinter WD4PF0CD0KP000000]"


def test_lienholder_vehicle_description_includes_decoded_model(monkeypatch):
    vehicle = SimpleNamespace(year=2020, make="MERCEDES-BENZ", model="", vin="WD4PF0CD0KP000000")

    monkeypatch.setattr(vehicle_utils, "decode_vin_nhtsa", lambda vin: {"Model": "SPRINTER"})

    assert _format_vehicle_for_description(vehicle) == "2020 MERCEDES-BENZ Sprinter (VIN: WD4PF0CD0KP000000)"
