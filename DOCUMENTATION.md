# 📖 Insurance Policy Intelligence Hub - Master Documentation

Welcome to the comprehensive technical and operational manual for the **Insurance Policy Intelligence Hub**. This document serves as the single source of truth for the system's architecture, data flows, core logic, and maintenance procedures.

---

## 📑 Table of Contents

1. [Architecture Deep Dive](#1-architecture-deep-dive)
2. [Extraction Pipeline (Universal Scout)](#2-extraction-pipeline-universal-scout)
3. [Coverage Ontology & Validation](#3-coverage-ontology--validation)
4. [API & Module Reference](#4-api--module-reference)
5. [Setup & Operations](#5-setup--operations)
6. [Data Flow & Communication](#6-data-flow--communication)
7. [UI & View Reference](#7-ui--view-reference)
8. [Utility & Helper Modules](#8-utility--helper-modules)
9. [COI Generation & Mapping](#9-coi-generation--mapping)
10. [Troubleshooting & FAQ](#10-troubleshooting--faq)
11. [Development Utilities](#11-development-utilities)
12. [Directory Map](#12-directory-map)

---

## 1. Architecture Deep Dive

The project follows a **Modified Layered Architecture**, designed for modularity, testability, and scalability.

### 1.1 High-Level Design

The system is divided into four primary layers:

- **Presentation Layer**: Streamlit-based UI (`app.py` and `views/`).
- **Service Layer**: Business logic and "glue" (`core/services.py`).
- **Intelligence Layer**: The AI-powered extraction pipeline (`modules/extraction/`).
- **Persistence Layer**: SQLAlchemy-managed SQLite database (`core/database.py`).

```mermaid
graph TD
    UI[Streamlit UI /app.py] --> Views[Views /views/]
    Views --> Services[Core Services /core/services.py]
    Services --> DB[(SQLite Database)]
    Views --> Extraction[Extraction Pipeline /modules/extraction/]
    Extraction --> Gemini[Google Gemini AI]
    Views --> COI[COI Generator /modules/coi/]
    COI --> PDF[PDF Templates]
    Services --> Ontology[Coverage Ontology /core/coverage_ontology.py]
```

### 1.2 Design Philosophy

- **Ontology-Driven**: The database schema and extraction schemas are derived from the `COVERAGE_REGISTRY` in `core/coverage_ontology.py`.
- **Stateless Extraction**: The extraction pipeline does not store state; it takes a PDF and returns normalized JSON. Persistence is handled by the Service layer.
- **Fail-Soft**: Each extraction step is wrapped in safety boundaries. If vehicle extraction fails, the policy and coverage extraction can still succeed.

---

## 2. Extraction Pipeline (Universal Scout)

The system uses a sophisticated, multi-stage pipeline powered by Google Gemini (2.0/2.5 Flash) to ensure high precision with minimal token costs.

### 2.1 Phase 0: Universal Scouting

The most critical addition to the v5 pipeline. Instead of guessing where data is, the system performs a full-document "scout" using the `UNIVERSAL_SCOUT_PROMPT`.

- **Purpose**: Identify exact page numbers for Premium, Vehicles, Drivers, and Coverages.
- **Benefit**: Reduces the amount of text sent to the heavy extraction models, drastically improving speed and accuracy.

### 2.2 Phase 2: Smart Slicing

The locator and scout findings are merged to create **Smart Slices**.

- **Logic**: For every page identified by the Scout, we expand the range by **+/- 1 page** to capture context (e.g., if a table spans two pages).
- **Parallelism**: The system then creates 4 separate PDF byte-slices and processes them in parallel using a `ThreadPoolExecutor`.

### 2.3 Phase 4: Assembly & Validation

Raw JSON responses from Gemini are merged into a unified `ExtractionContext`.

- **Unwrapping**: A recursive JSON parser (`_parse_json_response`) handles Gemini's occasional tendency to wrap responses in lists.
- **CSL Supremacy**: Python logic enforces that if a Combined Single Limit (CSL) is found, specific BI/PD splits are ignored to prevent data conflicts.

---

## 3. Coverage Ontology & Validation

The `core/coverage_ontology.py` is the "Rulebook" of the entire system.

### 3.1 The Registry (`COVERAGE_REGISTRY`)

Every coverage the system can find must exist here. It defines:

- **`family`**: e.g., `auto_liability`, `general_liability`.
- **`limit_structure`**: e.g., `csl`, `split`, `per_occurrence`.
- **`allowed_limits`**: Specifies which keys (e.g., `per_person`) are valid for that code.

### 3.2 Strict Validation Logic

The `validate_coverage()` function ensures adherence to the registry:

1. **Family Parity**: Rejects if the AI maps a coverage to the wrong family.
2. **Structure Check**: Rejects if a split limit is provided for a CSL code.
3. **Key Enforcement**: Strips any limit keys that aren't explicitly allowed in the registry for that code.

---

## 4. API & Module Reference

### 4.1 `PolicyService` (Core Service)

- `save_policy_from_extraction(result)`: Maps raw AI JSON to SQLAlchemy relationships.
- `ask_your_data(query)`: Translates NL to SQL, executes against SQLite, and returns results.

### 4.2 `GeminiExtractionPipeline` (Extraction Module)

- `run(file_bytes)`: The primary orchestrator.
- `_perform_extraction(ctx, processor)`: Manages the parallel threads for specialized extraction.

### 4.3 `UsageService` (Tracking)

- `log_usage(model, tokens)`: Calculates estimated USD cost based on token counts and model pricing.
- `is_over_budget()`: Provides a safety check to prevent runaway API spend.

---

## 5. Setup & Operations

### 5.1 Installation

1. Create a virtual environment: `python -m venv .venv`
2. Install dependencies: `pip install -r requirements.txt`
3. Configure API Key: Create a `.env` file with `GOOGLE_API_KEY=...`

### 5.2 Docker Deployment

The project includes a `Dockerfile` for containerized environments.

- **Build**: `docker build -t insurance-hub .`
- **Run**: `docker run -p 8501:8501 --env-file .env insurance-hub`

### 5.3 Database & Migration Logic

The system uses a custom, lightweight migration bridge in `core/database.py`.

- **Automatic Schema Updates**: On startup, `init_db()` inspects the existing SQLite schema and automatically performs `ALTER TABLE` commands if new columns have been added to the models. This ensures zero-downtime updates for local development.

### 5.4 Cache Management

The system uses a versioned cache in `.cache/extraction_cache/`.

- **To Clear Cache**: Delete the contents of this folder or increment `CACHE_VERSION` in `pipeline.py`.
- **Cache Logic**: Files are hashed; if the same file is uploaded twice with the same `CACHE_VERSION`, the AI is bypassed entirely.

### 5.3 Database Maintenance

The SQLite database `data/insurance_data.db` can be managed using standard SQL tools or the built-in **Database Management** page in the UI.

---

## 6. Data Flow & Communication

### 6.1 NL-to-SQL (Chat with Data)

The system uses a specialized prompt that provides the **full schema** to Gemini.

- **Safety**: Only `SELECT` statements are permitted. Semicolons are stripped.
- **Normalization**: The prompt instructs the AI on how to handle currency strings using SQLite `REPLACE()` and `CAST()`.

---

## 7. UI & View Reference

The frontend is built with **Streamlit** and located in the `views/` directory.

- **`dashboard.py`**: High-level business intelligence. Displays total policies, vehicle counts, and aggregate premiums using metrics cards and charts.
- **`process_policies.py`**: The extraction engine's primary interface. Handles PDF uploads, progress tracking, and intermediate review before database commit.
- **`database_page.py`**: CRUD interface for existing policies. Supports filtering by carrier, searching by policy number, and bulk deletion.
- **`edit_dialog.py`**: A modal component that allows users to manually correct AI-extracted values (e.g., typos in names or slightly off limit values) before finalizing the record.
- **`create_coi.py`**: The certificate generation workflow. Allows selection of a policy and holder, then triggers the COI generator.

---

## 8. Utility & Helper Modules

Located in `utils/`, these modules provide deterministic enhancements to AI output.

- **`vehicle_utils.py` (`refine_vehicle_type`)**: Enhances vehicle classification. If the AI provides a VIN and GVW, this utility uses weight-based logic (e.g., GVW > 26,000 lbs = "Tractor") to standardize vehicle types.
- **`naic_utils.py`**: Contains a dictionary of common insurance carriers and their NAIC numbers. Used as a fallback if the AI fails to find the NAIC code on the PDF.
- **`exporter.py`**: Uses `pandas` and `openpyxl` to generate formatted Excel reports from the SQLite policy table.

---

## 9. COI Generation & Mapping

The system generates ACORD 25 certificates using `modules/coi/`.

- **`generator.py`**: Uses the `pypdf` library to perform low-level form-filling. It injects data into the `data/COI Example.pdf` template.
- **`mapping.json`**: Acts as the translation layer. It maps human-friendly keys (e.g., `policy_number`) to the specific, technical Field IDs inside the ACORD PDF form.
- **`COIService.prepare_coi_data()`**: The pre-processing step that aggregates vehicles and drivers into descriptive strings for the "Description of Operations" box.

---

## 10. Troubleshooting & FAQ

### 10.1 "Quota Exceeded" Errors

- **Cause**: The Gemini API has per-minute and per-day token limits.
- **Solution**: Check the `Usage Dashboard` to see if you have hit your limit. Use the `ExtractionCache` to avoid re-processing existing files.

### 10.2 Missing Coverages

- **Cause**: The AI couldn't find a mapping in `COVERAGE_REGISTRY` or the text was too illegible.
- **Solution**: Check `modules/extraction/prompts.py` to ensure the registry is being passed correctly. Review the "Smart Slicing" pages to ensure the relevant text was in the slice.

### 10.3 Limit Parsing Errors

- **Cause**: Formats like "Split Limits" (100/300/50) can sometimes be misinterpreted as CSL.
- **Solution**: The `summarize_auto_liability` function in `core/coverage_ontology.py` is the deterministic source of truth. Check the logic there to see how it resolves conflicts.

---

## 11. Development Utilities

The `scripts/` directory contains tools for debugging and maintenance:

- **`check_models.py`**: A diagnostic script that verifies the database schema and prints current column structures.
- **`inspect_pdf.py`**: A utility for low-level inspection of PDF metadata and page count, useful for debugging slicing issues.

---

## 12. Directory Map

```text
/
├── app.py                # Main Entry Point
├── core/
│   ├── coverage_ontology.py # Registry & Validation
│   ├── database.py       # SQLAlchemy Schemas
│   └── services.py       # Business Services & NL2SQL
├── modules/
│   ├── extraction/       # AI Pipeline (Scout, Slice, Extract)
│   └── coi/              # PDF COI Generation
├── views/                # Streamlit Page modules
├── data/                 # SQLite DB, PDF Templates, Mappings
├── utils/                # Vehicle/NAIC/Export Helpers
├── assets/               # CSS & Styling
└── .cache/               # Extraction PDF Cache
```

---

_Document Version: 1.1 (January 2026)_
