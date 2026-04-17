import io
import textwrap
import pypdf
from datetime import datetime, date

class COIGenerator:
    def __init__(self, template_path="data/COI Example.pdf"):
        self.template_path = template_path

    def generate_coi(self, policy_data, holder_data, desc_font_size=8):
        """
        Fills the COI PDF template with policy and certificate holder data.
        """
        import json
        
        try:
            # Load Mappings
            try:
                import os
                base_dir = os.path.dirname(os.path.abspath(__file__))
                mapping_path = os.path.join(base_dir, "mapping.json")
                
                with open(mapping_path, "r") as f:
                    mapping_config = json.load(f)
                    field_map = mapping_config.get("mappings", {})
            except FileNotFoundError:
                print("Warning: mapping.json not found in module, using empty map.")
                field_map = {}

            reader = pypdf.PdfReader(self.template_path)
            writer = pypdf.PdfWriter()

            page = reader.pages[0]
            writer.add_page(page)
            
            # Fix: Copy /AcroForm from reader to writer to ensure form fields are recognized
            if "/AcroForm" in reader.trailer["/Root"]:
                writer.root_object.update({
                    pypdf.generic.NameObject("/AcroForm"): reader.trailer["/Root"]["/AcroForm"]
                })

            # Helper to format dates
            def fmt_date(d):
                if not d: return ""
                if isinstance(d, (datetime, date)):
                    return d.strftime("%m/%d/%Y")
                return "" # Return empty string for None/Text to let explicit strings pass if needed, or handle elsewhere
            
            # Helper to clean limits (remove text)
            def clean_limit(val):
                if not val: return ""
                # Keep only digits, commas, dots
                import re
                cleaned = re.sub(r'[^\d,.]', '', str(val))
                return f"${cleaned}" if cleaned else ""

            # Logic Flags
            has_gl = policy_data.get('has_general_liability', True) # Default to True if missing to be safe
            has_auto = policy_data.get('has_auto_liability', True)
            gl_occ = clean_limit(policy_data.get('liability_limit', '')) if has_gl else ""
            gl_agg = (
                clean_limit(policy_data.get('gl_general_aggregate') or policy_data.get('liability_limit', ''))
                if has_gl
                else ""
            )
            
            # Cargo Handling
            cargo_limit = clean_limit(policy_data.get('cargo_limit', ''))
            cargo_ded = clean_limit(policy_data.get('cargo_deductible', ''))
            has_cargo = bool(cargo_limit)
            
            # Description Construction
            # Vehicle List: [Year Model VIN]
            # Driver List: [Each driver names]
            # Radius of Operation: Unlimited
            # Certificate Holder is also listed as an additional insured
            
            desc_lines = []
            
            # Vehicles
            if policy_data.get('vehicle_list_str'):
                desc_lines.append(f"Vehicle List: {policy_data.get('vehicle_list_str')}")
            
            # Drivers
            if policy_data.get('driver_list_str'):
                desc_lines.append(f"Driver List: {policy_data.get('driver_list_str')}")
                
            # Note: Radius and Holder clause are now handled by the UI pre-fill in app.py
            # and passed via holder_data['description']
            
            if holder_data.get('description'):
                desc_lines.append(holder_data.get('description'))

            # Preserve natural section breaks only; let the PDF field auto-wrap within its bounds
            wrapped_lines = []
            for line in desc_lines:
                wrapped_lines.extend(line.splitlines() or [line])
            full_description = "\n".join(wrapped_lines)

            # Prepare the data dictionary
            # We construct the fields dict by looking up the PDF field name in our map
            
            # 1. Static/Hardcoded & Conditional "A"s
            fields = {
                # Document Date -> Current Date
                "F[0].P1[0].Form_CompletionDate_A[0]": datetime.now().strftime("%m/%d/%Y")
            }
            
            # Add "A" only if coverage exists, otherwise set to empty string to ensure it's cleared
            fields["F[0].P1[0].GeneralLiability_InsurerLetterCode_A[0]"] = "A" if has_gl else ""
            fields["F[0].P1[0].Vehicle_InsurerLetterCode_A[0]"] = "A" if has_auto else ""
            
            # Cargo usually falls under "Other"
            fields["F[0].P1[0].OtherPolicy_InsurerLetterCode_A[0]"] = "A" if has_cargo else ""
            
            # 2. Dynamic Mapping
            # (Key in JSON) -> (Value from Data)
            # 2. Dynamic Mapping
            # (Key in JSON) -> (Value from Data)
            
            # NAIC & Carrier
            # Assuming Mapping "Insurer_Name_A" -> "Insurer_FullName_A[0]"
            
            data_map = {
                "Insurer_Name_A": policy_data.get('carrier_name', ''),
                "Insurer_NAIC_A": policy_data.get('naic_number', ''),
                
                "PolicyNumber_GL": policy_data.get('policy_number', '') if has_gl else "",
                "EffectiveDate_GL": fmt_date(policy_data.get('effective_date')) if has_gl else "",
                "ExpirationDate_GL": fmt_date(policy_data.get('expiration_date')) if has_gl else "",
                "Limit_GL_Occurrence": gl_occ,
                "Limit_GL_FireDamage": "$100,000" if has_gl else "",
                "Limit_GL_MedExp": "$5,000" if has_gl else "",
                "Limit_GL_PersonalAdv": gl_occ,
                "Limit_GL_GeneralAggregate": gl_agg,
                "Limit_GL_ProductsAgg": gl_agg,
                
                "PolicyNumber_Auto": policy_data.get('policy_number', '') if has_auto else "",
                "EffectiveDate_Auto": fmt_date(policy_data.get('effective_date')) if has_auto else "",
                "ExpirationDate_Auto": fmt_date(policy_data.get('expiration_date')) if has_auto else "",
                "Limit_Auto_Combined": clean_limit(policy_data.get('liability_limit', '')) if has_auto else "",
                
                "Insured_Name": policy_data.get('insured_name', ''),
                "Insured_Address": policy_data.get('insured_address', ''),
                "Insured_City": policy_data.get('insured_city', ''),
                "Insured_State": policy_data.get('insured_state_code', ''),
                "Insured_Zip": policy_data.get('insured_zip', ''),
                
                "Holder_Name": holder_data.get('name', ''),
                "Holder_Address": holder_data.get('address', ''),
                "Holder_City": holder_data.get('city', ''),
                "Holder_State": holder_data.get('state', ''),
                "Holder_Zip": holder_data.get('zip', ''),
                "Holder_Description": full_description,
                
                # Cargo Section
                "Cargo_Box": "Motor Truck Cargo" if has_cargo else "",
                "Cargo_Limit": f"{cargo_limit} Cargo\n{cargo_ded} Ded" if has_cargo else "",
                "Cargo_Effective": fmt_date(policy_data.get('effective_date')) if has_cargo else "",
                "Cargo_Expires": fmt_date(policy_data.get('expiration_date')) if has_cargo else "",
                "Cargo_PolicyNumber": policy_data.get('policy_number', '') if has_cargo else ""
            }
            
            # Apply mappings
            for key, val in data_map.items():
                pdf_field_name = field_map.get(key)
                if pdf_field_name:
                    fields[pdf_field_name] = val
            
            writer.update_page_form_field_values(writer.pages[0], fields)

            output_buffer = io.BytesIO()
            writer.write(output_buffer)
            filled_pdf_bytes = output_buffer.getvalue()
            
            # 3. Flatten (Bake) the PDF using PyMuPDF (fitz)
            try:
                import fitz
                doc = fitz.open("pdf", filled_pdf_bytes)

                # Set font size on the description widget before baking
                desc_field_key = field_map.get("Holder_Description", "")
                for page in doc:
                    for widget in page.widgets():
                        wname = widget.field_name or ""
                        # PyMuPDF may return full path or just terminal segment
                        if wname == desc_field_key or desc_field_key.endswith(wname) or wname.endswith(desc_field_key):
                            widget.text_fontsize = desc_font_size
                            widget.update()
                            break

                # doc.bake() flattens all form fields and annotations across the document
                doc.bake()
                
                # Save to a new buffer
                flattened_buffer = io.BytesIO()
                doc.save(flattened_buffer)
                doc.close()
                return flattened_buffer.getvalue()
            except ImportError:
                print("Warning: PyMuPDF (fitz) not found. PDF will not be flattened/baked.")
                return filled_pdf_bytes
            except Exception as e:
                print(f"Error flattening PDF: {e}")
                # Fallback to filled but not flattened PDF if flattening fails
                return filled_pdf_bytes

        except Exception as e:
            # Re-raise to let the UI handle it or log it
            print(f"Error generating COI: {e}")
            raise e

if __name__ == "__main__":
    # Test
    gen = COIGenerator()
    dummy_policy = {
        "policy_number": "TEST-12345", 
        "effective_date": datetime(2023, 1, 1), 
        "expiration_date": datetime(2024, 1, 1),
        "liability_limit": "1,000,000",
        "insured_name": "Test Trucking Inc."
    }
    dummy_holder = {
        "name": "Test Holder",
        "address": "123 Main St",
        "city": "Springfield",
        "state": "IL",
        "zip": "62704"
    }
    pdf_bytes = gen.generate_coi(dummy_policy, dummy_holder)
    if pdf_bytes:
        with open("test_filled_coi.pdf", "wb") as f:
            f.write(pdf_bytes)
        print("Generated test_filled_coi.pdf")
