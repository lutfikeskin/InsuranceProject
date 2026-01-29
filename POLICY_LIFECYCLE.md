# Policy Extraction & Persistence Lifecycle

This document details the end-to-end journey of an insurance policy PDF as it moves through the **AI Insurance Document Platform**.

## 1. Ingestion & Optimization

### 1.1 Upload & hashing

- **User Action**: Drops a PDF into the "Process Policies" tab.
- **System**:
  - Reads the file bytes.
  - Computes a **SHA-256 hash** of the file content.
  - **Cache Check**: Queries `ExtractionCache` using the hash + schema version (`v6`).
    - _Hit_: Returns stored JSON immediately (Cost: $0, Time: <1s).
    - _Miss_: Proceeds to processing.

### 1.2 Remote Upload

- The raw PDF is uploaded to the **Gemini File API** for efficient remote processing.
- _Privacy_: This remote file is ephemeral and deleted immediately after the initial analysis phase.

---

## 2. Intelligence Phase (The "Smart Slicing" Architecture)

Before extracting data, the system builds a "map" of the document to minimize token usage and improve accuracy.

### 2.1 Classification

- **Model**: Gemini 2.5 Flash
- **Goal**: Determine `policy_type` (e.g., `commercial_auto`, `general_liability`).
- **Effect**: Loads specific **Validation Rules** (e.g., "Cargo" coverage is forbidden in "General Liability" policies).

### 2.2 Section Location

- **Model**: Gemini 2.5 Flash
- **Goal**: Identify page ranges for 4 key sections:
  1.  **Declarations** (Header data)
  2.  **Coverages** (Limits & Deductibles)
  3.  **Vehicles** (Schedule)
  4.  **Drivers** (Schedule)

### 2.3 Universal Scout

- **Model**: Gemini 2.5 Flash
- **Goal**: Scans the _entire_ document for "Signals" that might have been missed by the locator (e.g., a "Driver Schedule" hidden in an endorsement on page 45).
- **Merging**: The system mathematically fuses the "Locator" ranges and "Scout" signals into a **Final Section Map**.

---

## 3. Extraction Phase (Parallel Execution)

The system splits the PDF into smaller, focused bytes-chunks ("Slices") based on the Section Map. These slices are processed in **parallel**.

### 3.1 Declarations Extraction

- **Input**: Pages containing header info.
- **Output**: Policy number, dates, insured info, carrier name (using strict "Underwriter vs Agency" logic).

### 3.2 Coverage Extraction (The "Ontology Filter")

- **Input**: Dec pages + Coverage pages.
- **Prompt**: Dynamically generated based on the **Policy Type**.
  - _Example_: If `commercial_auto`, the AI is explicitly told _not_ to look for "General Aggregate".
- **Raw Output**: List of coverage objects with keys like `coverage_code`, `limits`, `deductible`.

### 3.3 Schedule Extraction (Conditional)

- **Vehicles**: Extracted only if policy type involves autos. Infers types (e.g., "Tractor", "Trailer") based on model names.
- **Drivers**: Extracted for auto policies. Flags "Excluded" drivers.

---

## 4. Validation & Normalization

This is where the "AI Slop" is cleaned into "Enterprise Data".

### 4.1 Coverage Validation (`validate_coverage`)

Every single extracted coverage is checked against the `COVERAGE_REGISTRY`:

1.  **Code Check**: Is extraction `AUTO_LIAB_BI` a valid code?
2.  **Family Check**: Does it belong to `auto_liability`?
3.  **Structure Check**: Does it have the required fields (e.g., `per_person` for Split limits)?
4.  **Deductible Check**: Physical Damage _must_ have a deductible or explicit "Full Glass" status.

- _Result_: Invalid coverages are silently discarded to prevent database pollution.

### 4.2 CSL Supremacy

- If the AI extracts both **Combined Single Limit (CSL)** and **Split Limits** (BI/PD) for Auto Liability, the system **prunes** the Split limits. CSL is the "Supreme" truth for that policy.

### 4.3 Summarization (New Feature)

The raw, validated data is condensed into high-level summary strings for the database:

- **UM/UIM**: "UM: 100/300 / UIM: 100/300"
- **Med Pay**: "5,000"
- **PIP**: "2,500"
- **Comp/Coll**: Extracts deductibles (e.g., "500", "1000") from the Physical Damage list.

---

## 5. Review & Persistence

### 5.1 The Review UI

- The normalized data is presented in the Streamlit "Process Policies" form.
- **Interactive**: The user can override any value (e.g., fix a typo in the VIN or adjust a limit).

### 5.2 Saving (`PolicyService`)

- **Action**: User clicks "Save to Database".
- **Logic**:
  1.  **Check Existence**: Does `policy_number` already exist?
  2.  **If New**: Inserts a new row in `policies` and child rows in `vehicles`, `assignments`, etc.
  3.  **If Existing**:
      - Triggers `HistoryService`.
      - **Diffing**: Compares the _new_ data vs. _db_ data.
      - **Versioning**: If changes are detected (e.g., "Liability Limit changed from 1M to 2M"), a new **PolicyHistory** version is created, and the main record is updated in-place.
      - **Scalar Mapping**: The new keys (`um_uim_limit`, etc.) are mapped to the scalar columns on the Policy object.

### 5.3 Final State

The policy is now active in the SQlite database (`insurance_data.db`), visible in the grid, and ready for export.
