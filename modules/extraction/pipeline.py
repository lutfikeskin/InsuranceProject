from google import genai
from google.genai import types
import os
import json
import tempfile
import time
import concurrent.futures
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, List, Any
from functools import lru_cache

# Internal Modules
from .pdf_ops import PdfProcessor
from core.coverage_ontology import (
    COVERAGE_REGISTRY, 
    POLICY_TYPE_CONSTRAINTS,
    summarize_auto_liability, 
    summarize_general_liability,
    summarize_cargo,
    validate_coverage, 
    is_coverage_allowed_for_policy_type,
    format_liability_limit
)

# Import schemas and prompts
from .schemas import (
    CLASSIFICATION_SCHEMA,
    SECTION_LOCATOR_SCHEMA,
    DECLARATIONS_SCHEMA,
    COVERAGE_SCHEMA,
    VEHICLE_SCHEMA,
    DRIVER_SCHEMA,
    PREMIUM_LOCATOR_SCHEMA
)

from .prompts import (
    CLASSIFY_POLICY_PROMPT,
    LOCATE_SECTIONS_PROMPT,
    EXTRACT_DECLARATIONS_PROMPT,
    EXTRACT_VEHICLES_PROMPT,
    EXTRACT_DRIVERS_PROMPT,
    get_coverages_prompt,
    LOCATE_PREMIUM_SIGNALS_PROMPT
)

# --- HELPERS ---

@lru_cache(maxsize=16)
def get_cached_registry_json(policy_type: str) -> str:
    """Cached generation of the registry JSON string to save tokens/CPU."""
    filtered_registry = {}
    constraints = POLICY_TYPE_CONSTRAINTS.get(policy_type)
    if constraints:
            allowed = set(constraints.get("allowed_families", []))
            forbidden = set(constraints.get("forbidden_codes", []))
            for code, entry in COVERAGE_REGISTRY.items():
                if entry["family"] in allowed and code not in forbidden:
                    filtered_registry[code] = entry
    else:
            filtered_registry = COVERAGE_REGISTRY
    return json.dumps(filtered_registry, indent=2)

# --- CONFIGURATION ---
ROUTING_MODEL = "gemini-2.0-flash"
EXTRACTION_MODEL = "gemini-2.0-flash"
CACHE_VERSION = "v4" # Increment this to invalidate all existing caches

MAX_PAGES = {
  "declarations": 8,
  "coverages": 8,
  "vehicles": 6,
  "drivers": 4
}

# --- STATE MANAGEMENT ---

@dataclass
class ExtractionContext:
    """Holds the state for a single extraction request."""
    file_bytes: bytes
    file_hash: str
    
    classification: dict = field(default_factory=dict)
    section_map: dict = field(default_factory=dict)
    extracted_data: dict = field(default_factory=dict) # Raw API responses
    
    # Normalized Results
    final_policy: dict = field(default_factory=dict)
    final_coverages: list = field(default_factory=list)
    final_vehicles: list = field(default_factory=list)
    final_drivers: list = field(default_factory=list)
    
    usage_metadata: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)

    @property
    def policy_type(self) -> str:
        return self.classification.get('policy_type', 'unknown')
        
    @property
    def confidence(self) -> str:
        return self.classification.get('confidence', 'unknown')


# --- PIPELINE CLASS ---

# --- CACHING ---
class ExtractionCache:
    def __init__(self, cache_dir=".cache/extraction_cache"):
        self.cache_dir = cache_dir
        self.index_file = os.path.join(cache_dir, "index.json")
        self._ensure_cache_exists()
        # self.lock = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def _ensure_cache_exists(self):
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir, exist_ok=True)
        if not os.path.exists(self.index_file):
            with open(self.index_file, 'w') as f:
                json.dump({}, f)

    def get(self, file_hash: str) -> Optional[dict]:
        # Versioned Key
        key = f"{CACHE_VERSION}_{file_hash}"
        try:
            cache_path = os.path.join(self.cache_dir, f"{key}.json")
            if os.path.exists(cache_path):
                with open(cache_path, 'r') as f:
                    print(f"CACHE HIT: {key}")
                    return json.load(f)
        except Exception as e:
            print(f"Cache Read Error: {e}")
        return None

    def save(self, file_hash: str, data: dict):
        key = f"{CACHE_VERSION}_{file_hash}"
        try:
            cache_path = os.path.join(self.cache_dir, f"{key}.json")
            with open(cache_path, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"CACHE SAVED: {key}")
        except Exception as e:
            print(f"Cache Write Error: {e}")

class GeminiExtractionPipeline:
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)

    def run(self, file_bytes: bytes, status_callback=None, force_refresh=False) -> tuple[dict, dict, str]:
        """
        Main Entry Point.
        Returns: (data, usage, error_message)
        """
        # 1. Initialize Context & Tools
        processor = PdfProcessor(file_bytes)
        ctx = ExtractionContext(
            file_bytes=file_bytes,
            file_hash=processor.get_hash()
        )
        
        # 0. Cache Check
        cache_system = ExtractionCache()
        cached_result = cache_system.get(ctx.file_hash)
        if cached_result and not force_refresh:
            return cached_result, {"source": "cache", "cost": 0}, None
        
        uploaded_file = None
        
        try:
            # 2. Upload (File API)
            print("Uploading to Gemini File API...")
            if status_callback: status_callback(" Uploading to Google AI Studio...")
            
            uploaded_file = self._upload_to_gemini(file_bytes)
            print(f"File uploaded: {uploaded_file.name}")
            
            # 3. Classify & Locate
            if status_callback: status_callback(" Classifying & Locating Sections...")
            
            # TODO: Add Caching here based on ctx.file_hash if needed in future
            
            ctx.classification = self._classify_policy(uploaded_file)
            print(f"Policy Type: {ctx.policy_type} ({ctx.confidence})")
            
            if ctx.policy_type == "unknown":
                return None, None, "Unknown Policy Type"

            ctx.section_map = self._locate_sections(uploaded_file)
            print(f"Section Map: {json.dumps(ctx.section_map, indent=2)}")


            # 3.5. Locate Premium Signals (NEW Two-Phase Logic)
            if status_callback: status_callback(" 🔍 Scouting for Premium Signals...")
            premium_pages = self._locate_premium_signals(uploaded_file)
            
            # Smart Merge: Add premium pages to 'declarations' slice
            # This ensures the extractor sees the invoice/summary pages even if Section Locator missed them.
            current_decs = set(ctx.section_map.get("declarations", []))
            # Expand range of each signal by +/- 1 page to catch context
            expanded_premium_pages = set()
            for p in premium_pages:
                expanded_premium_pages.add(p)
                expanded_premium_pages.add(p - 1)
                expanded_premium_pages.add(p + 1)
            
            # Filter valid pages (1 to total_pages)
            total_pages = processor.get_page_count()
            valid_premium_pages = {p for p in expanded_premium_pages if 1 <= p <= total_pages}
            
            final_dec_pages = current_decs.union(valid_premium_pages)
            ctx.section_map["declarations"] = sorted(list(final_dec_pages))
            print(f"  - Final Smart Slice (Declarations + Premium Signals): {ctx.section_map['declarations']}")

        except Exception as e:
            return None, None, f"Initialization Error: {str(e)}"
            
        finally:
            # 4. Cleanup Remote File (EARLY CLEANUP)
            if uploaded_file:
                try:
                    self.client.files.delete(name=uploaded_file.name)
                    print(f"Deleted remote file: {uploaded_file.name}")
                except Exception as e:
                    print(f"Warning: Failed to delete file: {e}")
            
            # AGREEMENT: Remote file is deleted immediately after section location.
            # This is SAFE because:
            # - All extraction steps use locally sliced PDF bytes
            # - No downstream call references uploaded_file
            # If future steps require Gemini visual grounding or page re-analysis, this deletion must be delayed.

        # 5. Extract (Parallel Sliced Execution)
        try:
            if status_callback: status_callback(" Starting Sliced Extraction...")
            self._perform_extraction(ctx, processor)
        except Exception as e:
            return None, None, f"Extraction Error: {str(e)}"

        # 6. Normalize & Validate
        final_result = self._assemble_result(ctx, processor)
        
        # 7. Cache Save
        try:
            cache_system.save(ctx.file_hash, final_result)
        except Exception as e:
            print(f"Failed to save cache: {e}")

        return final_result, ctx.usage_metadata, None

    # --- INTERNAL STEPS ---

    def _upload_to_gemini(self, file_bytes):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            return self.client.files.upload(file=tmp_path)
        finally:
            os.remove(tmp_path)

    def _classify_policy(self, uploaded_file) -> dict:
        response = self.client.models.generate_content(
            model=ROUTING_MODEL,
            contents=[uploaded_file, CLASSIFY_POLICY_PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=CLASSIFICATION_SCHEMA
            )
        )
        return self._parse_json_response(response.text)

    def _locate_sections(self, uploaded_file) -> dict:
        response = self.client.models.generate_content(
            model=ROUTING_MODEL,
            contents=[uploaded_file, LOCATE_SECTIONS_PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SECTION_LOCATOR_SCHEMA
            )
        )
        return self._parse_json_response(response.text)

    def _locate_premium_signals(self, uploaded_file) -> list:
        """Phase 1: Scan full document for pages containing premium/billing info."""
        try:
            print("  - Scanning for Premium Signals (Full PDF)...")
            response = self.client.models.generate_content(
                model=ROUTING_MODEL,
                contents=[uploaded_file, LOCATE_PREMIUM_SIGNALS_PROMPT],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=PREMIUM_LOCATOR_SCHEMA
                )
            )
            data = self._parse_json_response(response.text)
            signals = data.get("premium_signals", [])
            
            # Extract unique page numbers
            signal_pages = set()
            for s in signals:
                p = s.get("page_number")
                if isinstance(p, int):
                    signal_pages.add(p)
            
            print(f"  - Premium Signals found on pages: {sorted(list(signal_pages))}")
            return list(signal_pages)
        except Exception as e:
            print(f"Warning: Premium Signal Locator bad response: {e}")
            return []

    def _parse_json_response(self, text: str, ctx: Optional[ExtractionContext] = None) -> dict:
        """Centralized result parser to handle Gemini's list/dict inconsistency recursively."""
        try:
            data = json.loads(text)
            # Recursively unwrap lists until we find a dict
            while isinstance(data, list):
                if ctx:
                    # Observability: Track unwraps as signal of model struggle
                    ctx.usage_metadata["json_unwraps"] = ctx.usage_metadata.get("json_unwraps", 0) + 1
                    
                if not data: return {}
                data = data[0]
            
            if isinstance(data, dict):
                return data
            return {}
        except Exception as e:
            print(f"JSON Parse Error: {e}")
            return {}

    def _perform_extraction(self, ctx: ExtractionContext, processor: PdfProcessor):
        """Orchestrates parallel extraction using sliced PDFs."""
        
        # Prepare Slices
        sections = ["declarations", "coverages", "vehicles", "drivers"]
        slices = {}
        
        for section in sections:
            pages = self._get_pages_for_section(ctx.section_map, section, processor.get_page_count())
            pdf_bytes = processor.create_slice(pages)
            slices[section] = types.Part.from_bytes(data=pdf_bytes, mime_type='application/pdf')

        # Parallel Execution (Max Workers = 4)
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_decs = executor.submit(self._extract_declarations, slices["declarations"], ctx)
            future_cov = executor.submit(self._extract_coverages, slices["coverages"], ctx.policy_type, ctx)
            
            future_veh = None
            future_drv = None
            
            # Conditional Tasks
            if ctx.policy_type in ["personal_auto", "commercial_auto", "motor_truck_cargo", "umbrella"]:
                 future_veh = executor.submit(self._extract_vehicles, slices["vehicles"], ctx)
            
            if ctx.policy_type in ["personal_auto", "commercial_auto"]:
                 future_drv = executor.submit(self._extract_drivers, slices["drivers"], ctx)
                 
            # Wait & Store (Tuples from now on could be supported, but ctx passed is simpler for mutation)
            # Note: _extract_* methods now mutate ctx.usage_metadata internally or we just rely on return?
            # Keeping return simple for now, but passing ctx for JSON parser. 
            
            if future_decs: ctx.extracted_data["policy"] = future_decs.result()
            if future_cov: ctx.extracted_data["coverages"] = future_cov.result()
            
            if future_veh:
                ctx.extracted_data["vehicles"] = future_veh.result()
            if future_drv:
                ctx.extracted_data["drivers"] = future_drv.result()

    def _get_pages_for_section(self, section_map, section_name, total_pages):
        """Resolves 1-based Gemini pages to 0-based list, preserving sparse selections."""
        info = section_map.get(section_name, [])
        
        # GUARD: Empty slice optimization
        if info in (None, {}, []):
            return []
            
        selected_pages = []

        # Case A: List of Integers (e.g., [1, 2, 6]) - The Preferred Format
        if isinstance(info, list) and info and isinstance(info[0], int):
            selected_pages = [p - 1 for p in info if isinstance(p, int) and 1 <= p <= total_pages]
            
        # Case B: List of Dicts (Legacy fallback)
        elif isinstance(info, list) and info and isinstance(info[0], dict):
            # Take union of all ranges in the list
            possible_pages = set()
            for item in info:
                s = item.get("start_page", 1)
                e = item.get("end_page", total_pages)
                possible_pages.update(range(s - 1, min(e, total_pages)))
            selected_pages = sorted(list(possible_pages))
            
        # Case C: Single Integer (Legacy)
        elif isinstance(info, int):
            val = max(0, min(info - 1, total_pages - 1))
            selected_pages = [val]
            
        # Case D: Single Dict (Legacy)
        elif isinstance(info, dict):
            s = info.get("start_page", 1)
            e = info.get("end_page", total_pages)
            start_idx = max(0, s - 1)
            end_idx = min(e, total_pages)
            selected_pages = list(range(start_idx, end_idx))
            
        # Apply MAX_PAGES Cap (Take first N pages)
        max_p = MAX_PAGES.get(section_name, 10)
        if len(selected_pages) > max_p:
            print(f"Capping {section_name} from {len(selected_pages)} to {max_p} pages.")
            selected_pages = selected_pages[:max_p]
            
        return selected_pages

    # --- API WRAPPERS ---
    
    def _extract_declarations(self, part, ctx):
        res = self.client.models.generate_content(
            model=EXTRACTION_MODEL, contents=[part, EXTRACT_DECLARATIONS_PROMPT],
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=DECLARATIONS_SCHEMA)
        )
        return self._parse_json_response(res.text, ctx)

    def _extract_coverages(self, part, policy_type, ctx):
        # Use Cached Registry Helper
        registry_json = get_cached_registry_json(policy_type)

        prompt = get_coverages_prompt(registry_json, policy_type)
        res = self.client.models.generate_content(
            model=EXTRACTION_MODEL, contents=[part, prompt],
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=COVERAGE_SCHEMA)
        )
        return self._parse_json_response(res.text, ctx)

    def _extract_vehicles(self, part, ctx):
        res = self.client.models.generate_content(
            model=EXTRACTION_MODEL, contents=[part, EXTRACT_VEHICLES_PROMPT],
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=VEHICLE_SCHEMA)
        )
        return self._parse_json_response(res.text, ctx)

    def _extract_drivers(self, part, ctx):
        res = self.client.models.generate_content(
            model=EXTRACTION_MODEL, contents=[part, EXTRACT_DRIVERS_PROMPT],
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=DRIVER_SCHEMA)
        )
        return self._parse_json_response(res.text, ctx)

    # --- NORMALIZATION ---

    def _assemble_result(self, ctx: ExtractionContext, processor: PdfProcessor) -> dict:
        
        # 1. Base Policy Data
        final = {
            "policy": ctx.extracted_data.get("policy", {}),
            "coverages": [],
            "vehicles": ctx.extracted_data.get("vehicles", {}).get("vehicles", []),
            "drivers": ctx.extracted_data.get("drivers", {}).get("drivers", []),
            "classification": ctx.classification,
            "page_dimensions": processor.get_dimensions()
        }
        
        # 2. Validate Coverages
        raw_covs = ctx.extracted_data.get("coverages", {}).get("coverages", [])
        for c in raw_covs:
            # GUARD: specific fix for KeyError: 'coverage_code'
            code = c.get("coverage_code")
            if not code:
                continue
                
            if not is_coverage_allowed_for_policy_type(code, ctx.policy_type):
                continue
            is_valid, msg = validate_coverage(c)
            if is_valid:
                final["coverages"].append(c)

        # 3. Sanity Checks (CSL vs Split)
        self._apply_auto_liability_rules(final["coverages"], ctx.policy_type)
        
        # 4. Summarize Limits
        self._compute_summaries(final)
        
        return final

    def _apply_auto_liability_rules(self, coverages, policy_type):
        """Enforces CSL Supremacy and other checks."""
        if policy_type not in ["personal_auto", "commercial_auto"]:
            return
            
        auto_liabs = [c for c in coverages if c.get("family") == "auto_liability"]
        has_csl = any(c.get("limit_structure") == "csl" for c in auto_liabs)
        has_split = any(c.get("limit_structure") == "split" for c in auto_liabs)
        
        if has_csl and has_split:
            print("Refactor: Pruning Split limits in favor of CSL.")
            coverages[:] = [c for c in coverages if not (c.get("family") == "auto_liability" and c.get("limit_structure") == "split")]

    def _compute_summaries(self, final):
        # Auto Liab
        raw_summary = summarize_auto_liability(final["coverages"])
        if raw_summary:
            final["policy"]["liability_limit"] = format_liability_limit(raw_summary)
            
        # GL
        raw_gl = summarize_general_liability(final["coverages"])
        if raw_gl:
            final["policy"]["general_liability_limit"] = format_liability_limit(raw_gl)
            
        # Cargo
        raw_cargo = summarize_cargo(final["coverages"])
        if raw_cargo:
             final["policy"]["cargo_limit"] = f"${raw_cargo['value']:,}"
             if raw_cargo.get("deductible"):
                  final["policy"]["cargo_deductible"] = str(raw_cargo["deductible"])
        
        # Flags
        covs = final["coverages"]
        final["policy"]["has_auto_liability"] = any(c.get("family") == "auto_liability" for c in covs)
        final["policy"]["has_general_liability"] = any(c.get("family") == "general_liability" for c in covs)
        final["policy"]["has_full_collision"] = any(c.get("family") == "physical_damage" for c in covs)


# --- WRAPPER FOR BACKWARD COMPATIBILITY ---

def process_pdf(file_bytes, api_key, status_callback=None, force_refresh=False):
    """
    Wrapper function that instantiates the Pipeline Class.
    Maintains compatibility with views/process_policies.py
    """
    pipeline = GeminiExtractionPipeline(api_key=api_key)
    return pipeline.run(file_bytes, status_callback, force_refresh=force_refresh)
