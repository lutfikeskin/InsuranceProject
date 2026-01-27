---
trigger: always_on
---

# Project Rules — AI Insurance Document Platform

## 1. Core Mission

This project builds a **professional-grade AI insurance document platform** that:

- Reads insurance PDFs
- Classifies policy types
- Extracts structured, normalized data
- Enforces a strict coverage ontology
- Supports human verification, editing, and downstream document generation (COIs, forms, insights)

The system prioritizes **accuracy, determinism, auditability, and speed** over creativity or inference.

---

## 2. Non-Negotiable Principles

### 2.1 Ontology Is Law

- `COVERAGE_REGISTRY` is the **single source of truth**
- Every extracted coverage **must map** to a valid `coverage_code`
- No free-text or invented coverages
- If no valid mapping exists → omit the coverage

### 2.2 Determinism Over Intelligence

- AI extracts facts
- Python code applies logic
- AI must NEVER summarize limits, infer intent, or reconcile conflicts

### 2.3 Prefer Omission Over Guessing

- Missing data is acceptable
- Incorrect data is not
- If ambiguous → return `null` or exclude the field

---

## 3. AI Usage Rules

### 3.1 AI Is a Parser, Not a Decision Maker

AI may:

- Read PDFs
- Identify sections
- Extract explicit values
- Map coverages to ontology codes

AI may NOT:

- Decide which coverage “matters more”
- Combine limits
- Resolve CSL vs split conflicts
- Infer coverage existence

### 3.2 No Monolithic Prompts

- Extraction must be **section-based**
- Separate AI calls for:
  - Classification
  - Section detection
  - Declarations
  - Coverages
  - Vehicles
  - Drivers

### 3.3 Schema Enforcement Is Mandatory

- Every AI call must use a **strict response schema**
- Free-form JSON is forbidden
- Markdown output is forbidden

---

## 4. Policy Classification Rules

- Classification occurs **before extraction**
- Use lightweight models where possible
- If confidence is low:
  - Proceed cautiously
  - Never broaden scope
- `unknown` is a valid and acceptable result

---

## 5. Coverage Extraction Rules

### 5.1 CSL Supremacy

If a Combined Single Limit exists:

- Use `AUTO_LIAB_CSL`
- Ignore BI / PD
- Ignore UM / UIM
- Do not split limits

### 5.2 Split Limit Handling

If Bodily Injury and Property Damage are separate:

- BI → `AUTO_LIAB_BI`
- PD → `AUTO_LIAB_PD`
- Limits must be numeric and unformatted

### 5.3 UM / UIM Isolation

- UM/UIM must NEVER be classified as auto liability
- Families:
  - `uninsured_motorist`
  - `underinsured_motorist`

### 5.4 No Coverage Fabrication

- Do not assume coverage exists because it is “typical”
- Only extract explicitly stated coverages

---

## 6. Normalization & Validation

- All validation occurs **post-extraction**
- Use `validate_coverage()` for every coverage
- Invalid coverages are discarded silently
- Limit summaries are produced by:
  - `summarize_auto_liability()`
- AI must never generate summary strings

---

## 7. Performance Rules

- Minimize token usage
- Use section-scoped page ranges
- Cache:
  - Policy classification
  - Section locations
- Avoid reprocessing identical PDFs

Speed improvements must never reduce accuracy.

---

## 8. Manual Editing & Review

- All extracted data must remain editable
- AI output is **never final**
- Human corrections override AI data
- The system must preserve:
  - Original extracted values
  - Edited values
  - Validation status

---

## 9. Error Handling Philosophy

- Fail soft, not loud
- Partial extraction is acceptable
- One section failing must not block others
- Log errors without interrupting the pipeline

---

## 10. What This Project Is NOT

- Not a chatbot
- Not a “smart guesser”
- Not a document summarizer
- Not a replacement for licensed insurance judgment

---

## 11. Change Discipline

Any change must answer:

1. Does this preserve ontology integrity?
2. Does this reduce ambiguity?
3. Does this improve auditability?

If not — do not implement.

---

## 12. Final Rule

If there is a conflict between:

- AI output
- Python logic
- Ontology rules

**Ontology wins. Always.**

---
