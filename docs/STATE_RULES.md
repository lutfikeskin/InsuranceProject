# State Extraction Hints

Carrier formatting and terminology varies by state. These hints help the LLM correctly interpret what it sees in the document — they are NOT compliance checks or validation rules.

**Purpose**: Improve extraction accuracy by giving the LLM state-specific context about how coverages are typically written.

**NOT the purpose**: Checking whether the policy is legally compliant, flagging missing coverages, or validating minimum limits. If a coverage isn't in the document, we don't extract it. Period.

---

## Hints by State

### Texas (TX)
- UM/UIM is typically combined as a single line item. Use `UMUIM_*` codes unless clearly separated.

### Florida (FL)
- PIP appears on almost all auto policies — look for it on the declarations page.
- UM and UIM are typically listed separately with different limits.

### New York (NY)
- UIM may be labeled "SUM" (Supplementary Uninsured/Underinsured Motorist). Map to `UIM_*` codes.
- PIP appears on almost all auto policies.

### California (CA)
- UM/UIM typically listed separately.

### Ohio (OH)
- UM/UIM is typically combined. Use `UMUIM_*` codes unless clearly separated.

### New Jersey (NJ)
- May show "Basic" vs "Standard" policy type — extract whichever is present.

### Pennsylvania (PA)
- May show "Full Tort" or "Limited Tort" selection — note in policy metadata if visible.

---

## How These Are Used

During the extraction step, if the classification detects a state, the relevant hint is appended to the prompt. Example:

```
STATE CONTEXT (Texas):
UM/UIM is typically combined as a single line item. Use UMUIM_* codes unless clearly separated.
```

This is purely to help the LLM pick the right coverage code. No validation, no warnings, no compliance.

## How to Add New Hints

When you notice the LLM consistently misreading a coverage in a specific state's documents, add a hint here. Only add hints that directly improve extraction accuracy. Don't add rules about what "should" be in the document.
