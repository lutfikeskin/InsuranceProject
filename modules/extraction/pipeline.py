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
from core.logger import logger
from .pdf_ops import PdfProcessor
from utils.vehicle_utils import refine_vehicle_type
from modules.resolution.premium_resolver import audit_premium_extraction
from core.coverage_ontology import (
    COVERAGE_REGISTRY, 
    POLICY_TYPE_CONSTRAINTS,
    summarize_auto_liability, 
    summarize_general_liability,
    summarize_cargo,
    summarize_um_uim,
    summarize_med_pay,
    summarize_pip,
    summarize_physical_damage,
    validate_coverage, 
    is_coverage_allowed_for_policy_type,
    format_liability_limit
)
from core.database import get_session, create_engine
from core.services import UsageService

# Import schemas and prompts
from .schemas import (
    CLASSIFICATION_SCHEMA,
    SECTION_LOCATOR_SCHEMA,
    DECLARATIONS_SCHEMA,
    COVERAGE_SCHEMA,
    VEHICLE_SCHEMA,
    DRIVER_SCHEMA,
    UNIVERSAL_SCOUT_SCHEMA
)

from .prompts import (
    CLASSIFY_POLICY_PROMPT,
    LOCATE_SECTIONS_PROMPT,
    EXTRACT_DECLARATIONS_PROMPT,
    EXTRACT_VEHICLES_PROMPT,
    EXTRACT_DRIVERS_PROMPT,
    get_coverages_prompt,
    UNIVERSAL_SCOUT_PROMPT
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
ROUTING_MODEL = "gemini-2.5-flash"
EXTRACTION_MODEL = "gemini-2.5-flash"
CACHE_VERSION = "v9" # Determinism fix + Short Doc Strategy

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
    scout_map: dict = field(default_factory=dict) # Universal Scout Findings
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
                    logger.info(f"CACHE HIT: {key}")
                    return json.load(f)
        except Exception as e:
            logger.error(f"Cache Read Error: {e}")
        return None

    def save(self, file_hash: str, data: dict):
        key = f"{CACHE_VERSION}_{file_hash}"
        try:
            cache_path = os.path.join(self.cache_dir, f"{key}.json")
            with open(cache_path, 'w') as f:
                json.dump(data, f, indent=2)
            logger.debug(f"CACHE SAVED: {key}")
        except Exception as e:
            logger.error(f"Cache Write Error: {e}")

class GeminiExtractionPipeline:
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
        # Initialize usage tracking
        self.engine = create_engine("sqlite:///insurance_data.db")
        self.session = get_session(self.engine)
        self.usage_service = UsageService(self.session)

    def _validate_extraction_completeness(self, final_result, ctx):
        """Phase 4: Sanity Check - Detect Silent Failures using Scout Signals."""
        policy_type = final_result.get("classification", {}).get("policy_type")
        
        # Only check Auto-like policies
        if policy_type in ["personal_auto", "commercial_auto", "motor_truck_cargo", "commercial_package"]: # Added commercial_package
             has_vehs = len(final_result.get("vehicles", [])) > 0
             scout_has_vehs = len(ctx.scout_map.get("vehicle_schedule_signals", [])) > 0
             
             if scout_has_vehs and not has_vehs:
                 return False, "Silent Failure: Scout detected vehicles but extraction returned 0."
                 
        return True, "Passed"

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
            logger.info("Uploading to Gemini File API...")
            if status_callback: status_callback(" Uploading to Google AI Studio...")
            
            uploaded_file = self._upload_to_gemini(file_bytes)
            logger.info(f"File uploaded: {uploaded_file.name}")
            
            # 3. Classify & Locate
            if status_callback: status_callback(" Classifying & Locating Sections...")
            
            # TODO: Add Caching here based on ctx.file_hash if needed in future
            
            ctx.classification = self._classify_policy(uploaded_file)
            logger.info(f"Policy Type: {ctx.policy_type} ({ctx.confidence})")
            
            if ctx.policy_type == "unknown":
                return None, None, "Unknown Policy Type"

            # 3.1. Locate Sections (Broad Boundaries)
            ctx.section_map = self._locate_sections(uploaded_file)
            logger.info(f"Broad Slices (Locator): {json.dumps(ctx.section_map)}")

            # 3.5. Universal Scout (Specific Signals)
            if status_callback: status_callback(" 🔍 Running Universal Scout...")
            ctx.scout_map = self._run_universal_scout(uploaded_file)
            
            # --- INTELLIGENT MERGING ---
            total_pages = processor.get_page_count()

            def merge_pages(section_key, signal_key, signal_is_object_list=False):
                """Fuses broad section pages with discrete scout signals + context."""
                # Start with Locator findings
                current_pages = set(ctx.section_map.get(section_key, []))
                if section_key == "declarations" and total_pages > 0:
                    current_pages.add(1) # SAFETY FALLBACK: Always include Page 1 for Decs.
                
                # Extract pages from Scout
                scout_data = ctx.scout_map.get(signal_key, [])
                scout_pages = set()
                
                for item in scout_data:
                    if signal_is_object_list:
                         if isinstance(item, dict):
                            p = item.get("page")
                            if isinstance(p, int): scout_pages.add(p)
                    elif isinstance(item, int):
                        scout_pages.add(item)

                # Add context (+/- 1 page) to scout findings
                expanded_scout = set()
                for p in scout_pages:
                    expanded_scout.add(p)
                    expanded_scout.add(p - 1)
                    expanded_scout.add(p + 1)
                
                # Union and Validate range
                final_set = current_pages.union(expanded_scout)
                return sorted([p for p in final_set if 1 <= p <= total_pages])

            # Apply Merging Rules
            ctx.section_map = {
                "declarations": merge_pages("declarations", "premium_signals", signal_is_object_list=True),
                "vehicles": merge_pages("vehicles", "vehicle_schedule_signals"),
                "drivers": merge_pages("drivers", "driver_schedule_signals"),
                "coverages": merge_pages("coverages", "coverage_schedule_signals")
            }

            logger.info(f"Smart Slices (Merged): {json.dumps(ctx.section_map)}")

        except Exception as e:
            return None, None, f"Initialization Error: {str(e)}"
            
        finally:
            # 4. Cleanup Remote File (EARLY CLEANUP)
            if uploaded_file:
                try:
                    self.client.files.delete(name=uploaded_file.name)
                    logger.debug(f"Deleted remote file: {uploaded_file.name}")
                except Exception as e:
                    logger.warning(f"Failed to delete file: {e}")
            
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
        
        # 6b. Phase 4: Sanity Check
        # (Naive text signal assumption: checking raw text from first page as proxy for entire doc signal is costly here
        # so we will trust the extracted result internal logic for now, or just use Scout map)
        # Using Scout Map as "Text Signal" proxy
        # 6b. Phase 4: Sanity Check
        # (Naive text signal assumption: checking raw text from first page as proxy for entire doc signal is costly here
        # so we will trust the extracted result internal logic for now, or just use Scout map)
        # Using Scout Map as "Text Signal" proxy
        is_valid, sanity_msg = self._validate_extraction_completeness(final_result, ctx)
        if not is_valid:
            ctx.usage_metadata["sanity_failure"] = sanity_msg  # Log metadata
        
        if not is_valid:
            logger.warning(f"SANITY CHECK FAILED: {sanity_msg}")
            # We do NOT return error to user, but we do NOT cache this result.
            return final_result, ctx.usage_metadata, None # Return data, but don't cache

        # 7. Cache Save (Phase 5: Cache Guard)
        try:
            cache_system.save(ctx.file_hash, final_result)
        except Exception as e:
            logger.error(f"Failed to save cache: {e}")

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

    def _call_gemini(self, model: str, contents: list, config: types.GenerateContentConfig, request_type: str = "extraction"):
        """Centralized wrapper to enforce $2.50 daily budget and log usage."""
        if self.usage_service.is_over_budget(daily_limit=2.5):
             # Hard stop for safety
             raise Exception("STOPS: API Daily Quota Exceeded ($2.50). Processing halted to prevent billing.")
        
        # FORCE DETERMINISM: Temperature 0.0
        config.temperature = 0.0
        
        response = self.client.models.generate_content(
            model=model,
            contents=contents,
            config=config
        )
        
        # Log tokens if available
        if response.usage_metadata:
            self.usage_service.log_usage(
                model_name=model,
                input_tokens=response.usage_metadata.prompt_token_count,
                output_tokens=response.usage_metadata.candidates_token_count,
                request_type=request_type
            )
            
        return response

    def _classify_policy(self, uploaded_file) -> dict:
        response = self._call_gemini(
            model=ROUTING_MODEL,
            contents=[uploaded_file, CLASSIFY_POLICY_PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=CLASSIFICATION_SCHEMA
            ),
            request_type="classification"
        )
        return self._parse_json_response(response.text)

    def _locate_sections(self, uploaded_file) -> dict:
        response = self._call_gemini(
            model=ROUTING_MODEL,
            contents=[uploaded_file, LOCATE_SECTIONS_PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SECTION_LOCATOR_SCHEMA
            ),
            request_type="locator"
        )
        return self._parse_json_response(response.text)

    def _run_universal_scout(self, uploaded_file) -> dict:
        """Phase 1: Universal Scout - Scan full document for ALL key signals."""
        try:
            logger.info("Running Universal Scout (Full PDF)...")
            response = self._call_gemini(
                model=ROUTING_MODEL,
                contents=[uploaded_file, UNIVERSAL_SCOUT_PROMPT],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=UNIVERSAL_SCOUT_SCHEMA
                ),
                request_type="scout"
            )
            return self._parse_json_response(response.text)
        except Exception as e:
            logger.warning(f"Universal Scout failed: {e}")
            if "STOPS" in str(e): raise e # Critical quota stop
            return {}

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
            logger.error(f"JSON Parse Error: {e}")
            return {}

    def _perform_extraction(self, ctx: ExtractionContext, processor: PdfProcessor):
        """Orchestrates parallel extraction using sliced PDFs."""
        
        # Prepare Slices
        sections = ["declarations", "coverages", "vehicles", "drivers"]
        slices = {}
        
        # SHORT DOCUMENT STRATEGY:
        # If total pages <= 3, assume all info is dense/scatted.
        # Bypass slicing to prevent "slicing out" data if locator fails.
        total_pages = processor.get_page_count()
        is_short_doc = total_pages <= 3
        
        full_doc_bytes = None
        if is_short_doc:
             logger.info(f"SHORT DOC STRATEGY: Bypassing slicing for {total_pages} page(s). Using full doc.")
             full_doc_bytes = types.Part.from_bytes(data=ctx.file_bytes, mime_type='application/pdf')
        
        for section in sections:
            if is_short_doc:
                 slices[section] = full_doc_bytes
            else:
                pages = self._get_pages_for_section(ctx.section_map, section, processor.get_page_count())
                logger.info(f"PIPELINE: Slicing {section} -> Pages {pages}")
                pdf_bytes = processor.create_slice(pages)
                slices[section] = types.Part.from_bytes(data=pdf_bytes, mime_type='application/pdf')

        # Parallel Execution (Max Workers = 4)
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_decs = executor.submit(self._extract_declarations, slices["declarations"], ctx)
            future_cov = executor.submit(self._extract_coverages, slices["coverages"], ctx.policy_type, ctx)
            
            future_veh = None
            future_drv = None
            
            # Conditional Tasks
            # FIX: Allow 'commercial_package' (COIs often have GL+Auto)
            if ctx.policy_type in ["personal_auto", "commercial_auto", "motor_truck_cargo", "umbrella", "commercial_package"]:
                 future_veh = executor.submit(self._extract_vehicles, slices["vehicles"], ctx)
            
            if ctx.policy_type in ["personal_auto", "commercial_auto", "commercial_package"]:
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
        # GUARD: Empty slice optimization
        if info in (None, {}, []):
            # FIX: Fail Open for Safety
            # If we have NO info on where the section is, scanning the whole doc is safer 
            # than returning an empty PDF (which guarantees 0 results).
            return list(range(total_pages))
            
        selected_pages = []

        # Case A: List of Integers (Standardized)
        if isinstance(info, list) and info:
            # Flatten mixed list of ints/dicts just in case (e.g. from legacy cache)
            for item in info:
                if isinstance(item, int):
                    if 1 <= item <= total_pages:
                        selected_pages.append(item - 1)
                elif isinstance(item, dict):
                    # Handle legacy dict inside list if it somehow persists
                    s = item.get("start_page", 1)
                    e = item.get("end_page", total_pages)
                    # Convert range to pages
                    for p in range(max(1, s), min(e, total_pages) + 1):
                         selected_pages.append(p - 1)
            
            # Dedupe and Sort
            selected_pages = sorted(list(set(selected_pages)))
            
        # Legacy Cases B, C, D (Dict, Int, etc.) are REMOVED as Schema enforces List[Int]
            
        # Apply MAX_PAGES Cap (Take first N pages)
        max_p = MAX_PAGES.get(section_name, 10)
        if len(selected_pages) > max_p:
            logger.warning(f"Capping {section_name} from {len(selected_pages)} to {max_p} pages.")
            selected_pages = selected_pages[:max_p]
            
        return selected_pages

    # --- API WRAPPERS ---
    
    def _extract_declarations(self, part, ctx):
        res = self._call_gemini(
            model=EXTRACTION_MODEL, 
            contents=[part, EXTRACT_DECLARATIONS_PROMPT],
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=DECLARATIONS_SCHEMA),
            request_type="extraction_declarations"
        )
        return self._parse_json_response(res.text, ctx)

    def _extract_coverages(self, part, policy_type, ctx):
        # Use Cached Registry Helper
        registry_json = get_cached_registry_json(policy_type)

        prompt = get_coverages_prompt(registry_json, policy_type)
        res = self._call_gemini(
            model=EXTRACTION_MODEL, 
            contents=[part, prompt],
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=COVERAGE_SCHEMA),
            request_type="extraction_coverages"
        )
        return self._parse_json_response(res.text, ctx)

    def _extract_vehicles(self, part, ctx):
        scout_pages = ctx.scout_map.get("vehicle_schedule_signals", [])
        scout_hint = ""
        if scout_pages:
            # Flatten mixed list of ints/dicts just in case, though usually ints here
            cleaned_pages = []
            for p in scout_pages:
                 if isinstance(p, int): cleaned_pages.append(p)
                 elif isinstance(p, dict): cleaned_pages.append(p.get("page", 0))
            if cleaned_pages:
                 scout_hint = f"\nKNOWN VEHICLE SIGNAL PAGES: {sorted(list(set(cleaned_pages)))}\n"

        prompt = scout_hint + EXTRACT_VEHICLES_PROMPT
        res = self._call_gemini(
            model=EXTRACTION_MODEL, 
            contents=[part, prompt],
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=VEHICLE_SCHEMA),
            request_type="extraction_vehicles"
        )
        return self._parse_json_response(res.text, ctx)

    def _extract_drivers(self, part, ctx):
        scout_pages = ctx.scout_map.get("driver_schedule_signals", [])
        scout_hint = ""
        if scout_pages:
            cleaned_pages = []
            for p in scout_pages:
                 if isinstance(p, int): cleaned_pages.append(p)
                 elif isinstance(p, dict): cleaned_pages.append(p.get("page", 0))
            if cleaned_pages:
                 scout_hint = f"\nKNOWN DRIVER SIGNAL PAGES: {sorted(list(set(cleaned_pages)))}\n"

        prompt = scout_hint + EXTRACT_DRIVERS_PROMPT
        res = self._call_gemini(
            model=EXTRACTION_MODEL, 
            contents=[part, prompt],
            config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=DRIVER_SCHEMA),
            request_type="extraction_drivers"
        )
        return self._parse_json_response(res.text, ctx)

    # --- NORMALIZATION ---

    def _assemble_result(self, ctx: ExtractionContext, processor: PdfProcessor) -> dict:
        
        # 1. Base Policy Data
        final = {
            "policy": ctx.extracted_data.get("policy", {}),
            "coverages": [],
            "vehicles": [], # Will be populated by 1a
            "drivers": ctx.extracted_data.get("drivers", {}).get("drivers", []),
            "classification": ctx.classification,
            "page_dimensions": processor.get_dimensions()
        }

        # 1a. Refine Vehicles (The "Great System")
        raw_vehs = ctx.extracted_data.get("vehicles", {}).get("vehicles", [])
        for v in raw_vehs:
            refined = refine_vehicle_type(
                year=v.get('year'),
                make=v.get('make'),
                model=v.get('model'),
                vin=v.get('vin'),
                extracted_type=v.get('type'),
                extracted_chassis=v.get('chassis'),
                extracted_body=v.get('body')
            )
            v['type'] = refined['final_type']
            v['make'] = refined['make']
            v['model'] = refined['model']
            v['chassis'] = refined.get('chassis') or v.get('chassis')
            v['body'] = refined.get('body') or v.get('body')
            final["vehicles"].append(v)
        
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
        
        final["policy"]["has_full_collision"] = any(c.get("family") == "physical_damage" for c in final["coverages"])

        # 5. Premium Auditing (Resolver)
        # We need the page number of the extracted premium to check against Scout.
        # Check extraction metadata for premium location.
        prem_locs = final["policy"].get("field_locations", [])
        prem_page = None
        for loc in prem_locs:
            if loc.get("field") == "premium":
                prem_page = loc.get("page_number")
                break
        
        if prem_page:
            scout_signals = ctx.scout_map.get("premium_signals", [])
            audit_meta = audit_premium_extraction(prem_page, scout_signals)
            final["policy"]["premium_audit"] = audit_meta
            # Log the finding
            if audit_meta["confidence"] == "low":
                logger.warning(f"Premium Audit Warning: {audit_meta['flag']} on page {prem_page}")
            else:
                logger.info(f"Premium Audit: {audit_meta['flag']}")

        return final

    def _apply_auto_liability_rules(self, coverages, policy_type):
        """Enforces CSL Supremacy and other checks."""
        if policy_type not in ["personal_auto", "commercial_auto"]:
            return
            
        auto_liabs = [c for c in coverages if c.get("family") == "auto_liability"]
        has_csl = any(c.get("limit_structure") == "csl" for c in auto_liabs)
        has_split = any(c.get("limit_structure") == "split" for c in auto_liabs)
        
        if has_csl and has_split:
            logger.info("Refactor: Pruning Split limits in favor of CSL.")
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
        
        # New Summaries
        covs = final["coverages"]
        
        final["policy"]["um_uim_limit"] = summarize_um_uim(covs)
        final["policy"]["med_pay_limit"] = summarize_med_pay(covs)
        final["policy"]["pip_limit"] = summarize_pip(covs)
        
        phys_dam = summarize_physical_damage(covs)
        if phys_dam:
            final["policy"]["comp_deductible"] = phys_dam.get("comp")
            final["policy"]["coll_deductible"] = phys_dam.get("coll")

        # Flags
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
