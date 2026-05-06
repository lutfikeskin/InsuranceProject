# Insurance Document Platform - Database Schema

**Platform:** SQLite (Current) → PostgreSQL (Target)  
**ORM:** SQLAlchemy with declarative_base  
**Date:** 2026-05-05

---

## Entity Relationship Diagram (Text Format)

```
                          ┌─────────────────────┐
                          │    CUSTOMERS        │
                          │  (PK: id)           │
                          └──────────┬──────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
                    ▼                ▼                ▼
        ┌──────────────────────┐  ┌────────────────┐
        │  CUSTOMER_ENTITIES   │  │    POLICIES    │ ◄─────┐
        │  (FK: customer_id)   │  │  (FK: cust_id) │       │
        └──────────────────────┘  └────────┬───────┘       │
                                           │               │
                    ┌──────────────────────┼───────────────┼─────────────────┐
                    │                      │               │                 │
                    ▼                      ▼               ▼                 ▼
            ┌──────────────────┐  ┌──────────────┐  ┌────────────────┐  ┌──────────────────┐
            │    VEHICLES      │  │    DRIVERS   │  │   COVERAGES    │  │  ENDORSEMENTS    │
            │ (FK: policy_id)  │  │ (FK: policy) │  │(FK: policy,veh)│  │ (FK: policy_id)  │
            └────────┬─────────┘  └──────────────┘  └────────────────┘  └──────────────────┘
                     │
                     │ one vehicle → many coverages
                     └─────────────────┬──────────────┘
                                       ▼
                          (Coverage links to Vehicle)

            POLICY_RELATIONSHIPS (Self-join)
            ┌─────────────────────────────┐
            │  policy_id ──────► POLICIES │
            │  related_policy_id ──┐      │
            └─────────────────────────────┘

            ADDITIONAL_INTERESTS
            ┌──────────────────────┐
            │ (FK: policy_id)      │
            └──────────────────────┘

            API_USAGE (Monitoring)
            ┌──────────────────────┐
            │ (No FK - standalone) │
            └──────────────────────┘
```

---

## Table Inventory

| Table | Rows Est. | Purpose |
|-------|-----------|---------|
| customers | Low-Medium | Customer master record (personal names) |
| customer_entities | Low | Name variants (business, dba, maiden) |
| policies | Medium | Insurance policies with coverage summaries |
| vehicles | Medium | Vehicles insured under policies |
| drivers | Medium | Drivers associated with policies |
| coverages | High | Individual coverage lines (liability, collision, etc.) |
| policy_relationships | Medium | Renewal/rewrite links between policies |
| policy_endorsements | Low-Medium | Policy amendments and effective dates |
| additional_interests | Low-Medium | Certificate holders, loss payees, additional insureds |
| api_usage | High | Token usage and cost tracking |

---

## Detailed Table Schemas

### 1. CUSTOMERS
**Purpose:** Master customer record linked to all their policies.

| Column | Type | PK | FK | Nullable | Notes |
|--------|------|----|----|----------|-------|
| id | INTEGER | ✓ | | | Auto-increment |
| full_name | VARCHAR | | | ✗ | Personal name (anchor field) |
| primary_email | VARCHAR | | | ✓ | Contact email |
| primary_phone | VARCHAR | | | ✓ | Contact phone |
| needs_real_name_entry | BOOLEAN | | | | Default: false |
| created_at | DATETIME | | | | Default: NOW() |

**Relationships:**
- 1:M with `customer_entities` (delete-orphan cascade)
- 1:M with `policies` (no cascade)

---

### 2. CUSTOMER_ENTITIES
**Purpose:** Name variants for resolution (business name, DBA, maiden name).

| Column | Type | PK | FK | Nullable | Notes |
|--------|------|----|----|----------|-------|
| id | INTEGER | ✓ | | | Auto-increment |
| customer_id | INTEGER | | customers.id | | Foreign key |
| entity_name | VARCHAR | | | ✗ | Alternate name |
| entity_type | VARCHAR | | | ✓ | {personal, business, dba, maiden_name} |
| is_primary | BOOLEAN | | | | Default: false |
| source | VARCHAR | | | ✓ | {extraction, manual} |
| first_seen | DATETIME | | | | Default: NOW() |

**Relationships:**
- M:1 with `customers`

---

### 3. POLICIES
**Purpose:** Core policy record with extracted coverage summaries and classification.

| Column | Type | PK | FK | Nullable | Notes |
|--------|------|----|----|----------|-------|
| **Identifiers** |
| id | INTEGER | ✓ | | | Auto-increment |
| customer_id | INTEGER | | customers.id | ✓ | May be null (unmatched policies) |
| policy_number | VARCHAR | | | ✗ | Unique constraint |
| carrier_name | VARCHAR | | | ✗ | Insurer brand name |
| underwriter_name | VARCHAR | | | ✓ | Full legal name |
| naic_number | VARCHAR | | | ✓ | Carrier regulatory ID |
| **Coverage Summaries** |
| account_type | VARCHAR | | | ✓ | {Personal, Commercial} |
| policy_type | VARCHAR | | | ✓ | {personal_auto, commercial_auto, general_liability, ...} |
| document_type | VARCHAR | | | ✓ | {declarations_page, renewal_declarations, coi, endorsement, ...} |
| liability_limit | VARCHAR | | | ✓ | Rollup of auto liability limits (e.g., "50/100/50") |
| general_liability_limit | VARCHAR | | | ✓ | GL coverage summary |
| cargo_limit | VARCHAR | | | ✓ | Cargo liability amount |
| cargo_deductible | VARCHAR | | | ✓ | Cargo deductible |
| um_uim_limit | VARCHAR | | | ✓ | Uninsured/underinsured motorist limit |
| med_pay_limit | VARCHAR | | | ✓ | Medical payments limit |
| pip_limit | VARCHAR | | | ✓ | PIP coverage limit |
| comp_deductible | VARCHAR | | | ✓ | Comprehensive deductible |
| coll_deductible | VARCHAR | | | ✓ | Collision deductible |
| **Insured Info** |
| insured_name | VARCHAR | | | ✓ | Named insured |
| business_name | VARCHAR | | | ✓ | Business entity (if applicable) |
| insured_address | VARCHAR | | | ✓ | Street address |
| insured_city | VARCHAR | | | ✓ | City |
| insured_state_code | VARCHAR | | | ✓ | 2-letter state code |
| insured_zip | VARCHAR | | | ✓ | ZIP code |
| **Dates & Status** |
| effective_date | DATE | | | ✓ | Coverage start |
| expiration_date | DATE | | | ✓ | Coverage end |
| premium | VARCHAR | | | ✓ | Premium amount (stored as string for currency symbols) |
| status | VARCHAR | | | | Default: 'Active' |
| policy_status | VARCHAR | | | | Default: 'active' |
| **Classification** |
| classification_confidence | VARCHAR | | | ✓ | {low, medium, high} |
| classification_signals | VARCHAR | | | ✓ | JSON string of detection signals |
| **Flags & Metadata** |
| has_auto_liability | BOOLEAN | | | | Default: true |
| has_general_liability | BOOLEAN | | | | Default: true |
| has_full_collision | BOOLEAN | | | | Physical damage present |
| financial_responsibility_name | VARCHAR | | | ✓ | FR or named insured override |
| premium_audit_flag | VARCHAR | | | ✓ | {anomaly, missing, ok, ...} |
| field_confidences | JSON | | | ✓ | Per-field confidence scores |
| layout_fingerprint | VARCHAR | | | ✓ | Document layout hash |
| policy_data_source | VARCHAR | | | ✓ | {coi_summary, declarations_page, ...} |
| replaced_by_policy_id | INTEGER | | policies.id | ✓ | Self-reference for cancellation/replacement |
| extraction_extras | TEXT | | | ✓ | JSON of unmapped ontology fields |
| state | VARCHAR | | | ✓ | Policy state (may differ from insured_state) |
| created_at | DATETIME | | | | Default: NOW() |

**Relationships:**
- M:1 with `customers` (nullable)
- 1:M with `vehicles` (delete-orphan cascade)
- 1:M with `drivers` (delete-orphan cascade)
- 1:M with `coverages` (delete-orphan cascade)
- 1:M with `policy_relationships` (delete-orphan cascade, two directions)
- 1:M with `additional_interests` (delete-orphan cascade)
- 1:M with `policy_endorsements` (delete-orphan cascade)
- 1:M with `policy_history` (delete-orphan cascade)

---

### 4. VEHICLES
**Purpose:** Vehicles insured under a policy.

| Column | Type | PK | FK | Nullable | Notes |
|--------|------|----|----|----------|-------|
| id | INTEGER | ✓ | | | Auto-increment |
| policy_id | INTEGER | | policies.id | | Foreign key |
| year | INTEGER | | | ✓ | Model year |
| make | VARCHAR | | | ✓ | Manufacturer |
| model | VARCHAR | | | ✓ | Model name |
| vin | VARCHAR | | | ✓ | Vehicle identification number |
| vehicle_type | VARCHAR | | | ✓ | {sedan, truck, motorcycle, ...} |
| gvwr | INTEGER | | | ✓ | Gross vehicle weight rating |
| chassis | VARCHAR | | | ✓ | Chassis type |
| body | VARCHAR | | | ✓ | Body style |

**Relationships:**
- M:1 with `policies`
- 1:M with `coverages` (vehicle-specific coverages)

---

### 5. DRIVERS
**Purpose:** Drivers associated with a policy.

| Column | Type | PK | FK | Nullable | Notes |
|--------|------|----|----|----------|-------|
| id | INTEGER | ✓ | | | Auto-increment |
| policy_id | INTEGER | | policies.id | | Foreign key |
| full_name | VARCHAR | | | ✓ | Driver name |
| license_number | VARCHAR | | | ✓ | License plate or ID |
| is_excluded | BOOLEAN | | | | Default: false |

**Relationships:**
- M:1 with `policies`

---

### 6. COVERAGES
**Purpose:** Individual coverage lines mapped to ontology (UM_BI, AUTO_LIAB_PD, COMP, etc.).

| Column | Type | PK | FK | Nullable | Notes |
|--------|------|----|----|----------|-------|
| id | INTEGER | ✓ | | | Auto-increment |
| policy_id | INTEGER | | policies.id | | Foreign key |
| vehicle_id | INTEGER | | vehicles.id | ✓ | Optional (policy-wide coverage) |
| **Display** |
| type | VARCHAR | | | ✓ | Legacy name (e.g., "Bodily Injury") |
| coverage_code | VARCHAR | | | ✓ | Ontology code (e.g., AUTO_LIAB_BI, COMP) |
| family | VARCHAR | | | ✓ | Category (e.g., auto_liability, physical_damage) |
| **Limits (Ontology)** |
| per_person | INTEGER | | | ✓ | Bodily injury per person |
| per_accident | INTEGER | | | ✓ | Per accident/incident limit |
| per_occurrence | INTEGER | | | ✓ | Per occurrence limit (GL) |
| combined_single_limit | INTEGER | | | ✓ | CSL (single combined limit) |
| aggregate | INTEGER | | | ✓ | Aggregate limit |
| **Legacy Aliases** |
| limit_per_person | INTEGER | | | ✓ | Backward compatibility |
| limit_per_accident | INTEGER | | | ✓ | Backward compatibility |
| limit_property_damage | INTEGER | | | ✓ | Maps to per_occurrence |
| deductible | INTEGER | | | ✓ | Deductible amount |

**Relationships:**
- M:1 with `policies`
- M:1 with `vehicles` (optional)

---

### 7. POLICY_RELATIONSHIPS
**Purpose:** Links between policies (renewals, rewrites, replacements).

| Column | Type | PK | FK | Nullable | Notes |
|--------|------|----|----|----------|-------|
| id | INTEGER | ✓ | | | Auto-increment |
| policy_id | INTEGER | | policies.id | | From policy |
| related_policy_id | INTEGER | | policies.id | | To policy (self-join) |
| relationship_type | VARCHAR | | | ✓ | {renewal, rewrite, mid_term_change, same_customer_new_policy, canceled_replaced} |
| confidence | VARCHAR | | | ✓ | {confirmed, suggested} |
| created_at | DATETIME | | | | Default: NOW() |

**Relationships:**
- M:1 with `policies` (policy → related)
- M:1 with `policies` (related ← policy)

---

### 8. POLICY_ENDORSEMENTS
**Purpose:** Policy amendments (coverage changes, effective dates).

| Column | Type | PK | FK | Nullable | Notes |
|--------|------|----|----|----------|-------|
| id | INTEGER | ✓ | | | Auto-increment |
| parent_policy_id | INTEGER | | policies.id | ✓ | Endorsement applies to this policy |
| parent_policy_number | VARCHAR | | | ✓ | Policy number reference |
| endorsement_type | VARCHAR | | | ✓ | Type of amendment |
| endorsement_form_number | VARCHAR | | | ✓ | Form reference (e.g., CA 99 10 03) |
| effective_date | DATE | | | ✓ | When amendment takes effect |
| changes_summary | TEXT | | | ✓ | What changed |
| file_hash | VARCHAR | | | ✓ | Deduplication hash |
| created_at | DATETIME | | | | Default: NOW() |

**Relationships:**
- M:1 with `policies`

---

### 9. ADDITIONAL_INTERESTS
**Purpose:** Certificate holders, additional insureds, loss payees.

| Column | Type | PK | FK | Nullable | Notes |
|--------|------|----|----|----------|-------|
| id | INTEGER | ✓ | | | Auto-increment |
| policy_id | INTEGER | | policies.id | | Foreign key |
| name | VARCHAR | | | ✓ | Entity name |
| address | VARCHAR | | | ✓ | Mailing address |
| interest_type | VARCHAR | | | ✓ | {Certificate Holder, Additional Insured, Loss Payee, ...} |

**Relationships:**
- M:1 with `policies`

---

### 10. API_USAGE
**Purpose:** Token usage tracking for Gemini API cost monitoring.

| Column | Type | PK | FK | Nullable | Notes |
|--------|------|----|----|----------|-------|
| id | INTEGER | ✓ | | | Auto-increment |
| timestamp | DATETIME | | | | Default: NOW() |
| model_name | VARCHAR | | | ✓ | Model used (e.g., gemini-2.5-flash) |
| input_tokens | INTEGER | | | ✓ | Tokens sent to API |
| output_tokens | INTEGER | | | ✓ | Tokens returned from API |
| cost | FLOAT | | | ✓ | Estimated USD cost |
| status | VARCHAR | | | ✓ | {success, failure} |
| request_type | VARCHAR | | | ✓ | {scout, extraction, query, ...} |

**Relationships:**
- None (monitoring table)

---

### 11. POLICY_HISTORY
**Purpose:** Audit trail of policy changes (late import from `core.history_model`).

| Column | Type | PK | FK | Nullable | Notes |
|--------|------|----|----|----------|-------|
| id | INTEGER | ✓ | | | Auto-increment |
| policy_id | INTEGER | | policies.id | | Foreign key |
| timestamp | DATETIME | | | | Change timestamp |
| field_name | VARCHAR | | | ✓ | Which field changed |
| old_value | TEXT | | | ✓ | Previous value |
| new_value | TEXT | | | ✓ | New value |
| change_source | VARCHAR | | | ✓ | {extraction, manual, system} |

**Relationships:**
- M:1 with `policies`

---

## Key Constraints & Indexes (Recommended for PostgreSQL)

### Primary Keys
All tables have `id` as auto-incrementing primary key.

### Unique Constraints
- `policies.policy_number` — No two policies with same number

### Foreign Keys
See relationship columns in each table (marked as FK).

### Recommended Indexes (Performance)
```sql
-- Policy lookups
CREATE INDEX idx_policies_customer_id ON policies(customer_id);
CREATE INDEX idx_policies_policy_number ON policies(policy_number);
CREATE INDEX idx_policies_carrier ON policies(carrier_name);
CREATE INDEX idx_policies_policy_type ON policies(policy_type);

-- Coverage queries
CREATE INDEX idx_coverages_policy_id ON coverages(policy_id);
CREATE INDEX idx_coverages_coverage_code ON coverages(coverage_code);
CREATE INDEX idx_coverages_vehicle_id ON coverages(vehicle_id);

-- Vehicle queries
CREATE INDEX idx_vehicles_policy_id ON vehicles(policy_id);
CREATE INDEX idx_vehicles_vin ON vehicles(vin);

-- Driver queries
CREATE INDEX idx_drivers_policy_id ON drivers(policy_id);

-- Relationships
CREATE INDEX idx_policy_rels_policy_id ON policy_relationships(policy_id);
CREATE INDEX idx_policy_rels_related_policy_id ON policy_relationships(related_policy_id);

-- Endorsements
CREATE INDEX idx_endorsements_policy_id ON policy_endorsements(parent_policy_id);

-- Additional interests
CREATE INDEX idx_interests_policy_id ON additional_interests(policy_id);

-- API usage (time-series)
CREATE INDEX idx_api_usage_timestamp ON api_usage(timestamp);
CREATE INDEX idx_api_usage_request_type ON api_usage(request_type);
```

---

## Migration Notes for PostgreSQL

1. **Data Type Conversions:**
   - INTEGER → BIGINT (if scaling beyond 2B rows)
   - VARCHAR → VARCHAR(255) with appropriate lengths per column
   - BOOLEAN → BOOLEAN (native in PostgreSQL)
   - DATETIME → TIMESTAMP with timezone
   - TEXT → TEXT (native support)
   - JSON → JSONB (for field_confidences, classification_signals)

2. **Cascade Deletions:**
   - All relationships use `cascade="all, delete-orphan"` in SQLAlchemy
   - PostgreSQL: Use `ON DELETE CASCADE` for foreign keys

3. **Nullable vs Not Null:**
   - `customers.full_name` — NOT NULL
   - `policies.policy_number` — NOT NULL, UNIQUE
   - All other fields — default to NULL

4. **Alembic Migrations:**
   - Keep existing migrations immutable
   - Add new .py files for PostgreSQL-specific changes (e.g., JSONB, BIGSERIAL)

5. **Sequence Creation:**
   - PostgreSQL auto-creates `tablename_id_seq` for SERIAL/BIGSERIAL columns
   - SQLAlchemy handles this transparently

6. **Performance Tuning (Post-Migration):**
   - Add indexes (see above)
   - Partition large tables (api_usage by timestamp, coverages by policy_type)
   - Vacuum and analyze after initial load

---

## Summary Statistics

| Metric | Value |
|--------|-------|
| Total Tables | 11 |
| Total Columns | ~130 |
| Foreign Key Relationships | 18 |
| Self-Referencing Tables | 2 (policies, policy_relationships) |
| Cascade Delete Relationships | 8 |

