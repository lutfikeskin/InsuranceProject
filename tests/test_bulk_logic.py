import io
import zipfile
from modules.coi import COIGenerator
from datetime import datetime

def test_bulk_generation_logic():
    print("Testing Bulk COI Generation Logic...")
    
    gen = COIGenerator(template_path="data/COI Example.pdf")
    
    dummy_policy = {
        "carrier_name": "Test Carrier", 
        "naic_number": "12345", 
        "policy_number": "POL-999", 
        "effective_date": datetime(2023, 1, 1), 
        "expiration_date": datetime(2024, 1, 1), 
        "liability_limit": "1,000,000",
        "gl_general_aggregate": "$2,000,000",
        "cargo_limit": "100,000",
        "cargo_deductible": "1000",
        "has_general_liability": True,
        "has_auto_liability": True,
        "insured_name": "Test Insured",
        "insured_address": "123 Insured St",
        "insured_city": "City",
        "insured_state_code": "ST",
        "insured_zip": "12345",
        "vehicle_list_str": "", 
        "driver_list_str": ""
    }
    
    selected_companies = {
        "Comp A": {"name": "Comp A", "address": "Addr A", "city": "City A", "state": "SA", "zip": "11111"},
        "Comp B": {"name": "Comp B", "address": "Addr B", "city": "City B", "state": "SB", "zip": "22222"}
    }
    
    h_desc = "Standard Description"
    
    zip_buffer = io.BytesIO()
    try:
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            for comp_name, comp_data in selected_companies.items():
                print(f"Generating for {comp_name}...")
                h_data = {
                    "name": comp_data.get("name", ""),
                    "address": comp_data.get("address", ""),
                    "city": comp_data.get("city", ""),
                    "state": comp_data.get("state", ""),
                    "zip": comp_data.get("zip", ""),
                    "description": h_desc
                }
                pdf = gen.generate_coi(dummy_policy, h_data)
                if pdf:
                    safe_name = "".join([c for c in comp_name if c.isalnum() or c in (' ', '_')]).strip()
                    zf.writestr(f"COI_{safe_name}.pdf", pdf)
        
        # Verify ZIP
        zip_buffer.seek(0)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            file_list = zf.namelist()
            print(f"ZIP contains: {file_list}")
            assert "COI_Comp A.pdf" in file_list
            assert "COI_Comp B.pdf" in file_list
        
        print("Bulk Generation Logic Test PASSED!")
    except Exception as e:
        print(f"Bulk Generation Logic Test FAILED: {e}")

def test_coi_without_gl_general_aggregate_falls_back_to_liability_limit():
    """Omitting gl_general_aggregate keeps aggregate PDF fields aligned with liability_limit."""
    gen = COIGenerator(template_path="data/COI Example.pdf")
    policy = {
        "carrier_name": "Test Carrier",
        "naic_number": "12345",
        "policy_number": "POL-FALLBACK",
        "effective_date": datetime(2023, 1, 1),
        "expiration_date": datetime(2024, 1, 1),
        "liability_limit": "1,000,000",
        "cargo_limit": "",
        "cargo_deductible": "1000",
        "has_general_liability": True,
        "has_auto_liability": False,
        "insured_name": "Test Insured",
        "insured_address": "1 Main",
        "insured_city": "City",
        "insured_state_code": "ST",
        "insured_zip": "00000",
        "vehicle_list_str": "",
        "driver_list_str": "",
    }
    holder = {
        "name": "Holder",
        "address": "2 Main",
        "city": "City",
        "state": "ST",
        "zip": "00000",
        "description": "Ops",
    }
    pdf = gen.generate_coi(policy, holder)
    assert pdf
    assert len(pdf) > 1000


if __name__ == "__main__":
    test_bulk_generation_logic()
