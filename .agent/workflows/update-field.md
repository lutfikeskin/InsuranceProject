---
description: How to add or update a data field across the entire application stack
---

When adding or updating a field in `extractor.py`, you **MUST** propagate that change to the following layers to ensure consistency.

1. **Extraction Logic** (`extractor.py`)
   - Update the system instruction prompt.
   - Update the JSON schema.

2. **Database Schema** (`database.py`)
   - Check if the field exists in the `Policy` model.
   - If not, add `Column(...)` definition.
   - Update `init_db` to handle migration (sqlite `ALTER TABLE`) if necessary.

3. **Service Layer** (`services.py`)
   - Update `save_policy_from_extraction` to map the new JSON field to the database model.
   - Update `update_policy` if special handling is needed.

4. **Policy Preview / Processing IO** (`views/process_policies.py`)
   - Update the `st.json` or custom display logic to show this new field to the user _before_ they save.
   - Ensure it's included in any manual edit forms in this view.

5. **Database View** (`views/database_page.py`)
   - Add the column to the `data_list` construction loop.
   - Update the `st.dataframe` configuration if necessary (e.g. column config).
   - Update the **Edit Dialog** (`views/edit_dialog.py`) to allow editing this field.

6. **Exports** (`exporter.py`, `coi_generator.py`)
   - Ensure the field is included in Excel exports if relevant.
   - Check if this field needs to map to the COI PDF.
