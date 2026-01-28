# Insurance Policy Intelligence Hub

A Streamlit-based application for extracting data from insurance policy PDFs using Google Gemini AI, managing policy history in a local database, and automatically generating Certificates of Insurance (COI).

> [!TIP]
> **New to the project?** Read the [Full Project Guide](file:///c:/Users/Lutfi/Documents/InsuranceProject/GUIDE.md) for a deep dive into the architecture, data flows, and module structure.

## Features

- **AI Extraction**: Upload PDF policies to extract key data (Limits, Dates, Coverages, Drivers, Vehicles) using Google Gemini 2.5 Flash.
  - **High-Precision Scouting**: Uses a multi-phase "Universal Scout" + "Smart Slicing" architecture to find signals before extraction.
- **Data Management**: View, filter, edit, and delete extracted policies from a local SQLite database.
- **COI Generation**: Select a policy, pick a certificate holder, and generate a pre-filled PDF Certificate of Insurance.
  - **Auto-Logic**: Automatically hides/shows "General Liability", "Auto", and "Cargo" sections based on coverage presence.
  - **Smart Formatting**: Pre-fills the "Description of Operations" with vehicle/driver lists and required clauses.
  - **NAIC Lookup**: Auto-populates NAIC codes for major carriers (Progressive, GEICO) if missing from the extraction.
- **Excel Export**: Download your entire policy history as an Excel report.

## Setup & Installation

### Prerequisites

- Python 3.10+
- Google Cloud API Key for Gemini (AI Studio)

### Installation

1.  **Clone/Download** the repository.
2.  **Install Dependencies**:

    ```bash
    pip install -r requirements.txt
    ```

    _(Key libraries: `streamlit`, `google-generativeai`, `sqlalchemy`, `pandas`, `pypdf`, `openpyxl`)_

3.  **Configure API Key**:
    - The app allows you to enter your key in the "Settings" menu.
    - Alternatively, create a `.streamlit/secrets.toml` file:
      ```toml
      GEMINI_API_KEY = "your_api_key_here"
      ```

## Usage

1.  **Run the Application**:

    ```bash
    streamlit run app.py
    ```

2.  **Process Policies**:
    - Go to **Process Policies** tab.
    - Drag & Drop PDF files.
    - Click **Start Extraction**.
    - Review Extracted Data, Compare with the source material PDF and make adjustments if needed before daving to the database.
    - Control all the data in the **Dashboard** or **Database** tab.
    - Communicate with the AI Powered Chatbot in the Database for specific information requests in a conversation-like style.

3.  **Generate COI**:
    - Go to **Create COI** tab.
    - Select a Policy from the dropdown.
    - Select or Enter Certificate Holder details.
    - Review the "Insured Details" and "Operations Description" (fully editable).
    - Click **Generate & Download PDF**.

## Project Structure

- **`app.py`**: Streamlit application handling the UI and routing.
- **`extractor.py`**: Interacts with Google Gemini to parse PDF text into structured JSON.
- **`database.py`**: Defines the SQLite database schema (`insurance_data.db`) using SQLAlchemy.
- **`coi_generator.py`**: Handles filling the `COI Example.pdf` template with data.
- **`coi_mapping.json`**: Maps internal database fields to the PDF form field names.
- **`naic_utils.py`**: Helper dictionary for looking up NAIC codes by Carrier Name.
- **`coi_utils.py`**: Utility for loading company data (Certificate Holders) from Excel.

## Customization

- **Template**: Replace `COI Example.pdf` with your own ACORD form if needed (ensure field names match or update `coi_mapping.json`).
- **NAIC Codes**: Add more carriers to `naic_utils.py` to expand the auto-lookup coverage.
