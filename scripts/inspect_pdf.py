import pypdf

def inspect_pdf_fields(pdf_path):
    try:
        reader = pypdf.PdfReader(pdf_path)
        fields = reader.get_fields()
        
        if fields:
            print(f"Found {len(fields)} fields:")
            for field_name, value in fields.items():
                field_type = value.get('/FT')
                print(f" - Name: {field_name}, Type: {field_type}")
        else:
            print("No form fields found in the PDF.")
            
    except Exception as e:
        print(f"Error reading PDF: {e}")

if __name__ == "__main__":
    inspect_pdf_fields("COI Example.pdf")
