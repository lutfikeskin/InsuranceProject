from google import genai
from google.genai import types
import os
import json
import tempfile
import time

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
from functools import lru_cache

# Internal Modules
from core.logger import logger
from .pdf_ops import PdfProcessor
from utils.vehicle_utils import refine_vehicle_type

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

from .knowledge_base import CarrierKnowledgeBase

# Import schemas and prompts
from .schemas import (
    CLASSIFICATION_SCHEMA,
    DECLARATIONS_SCHEMA,
    COVERAGE_SCHEMA,
    VEHICLE_SCHEMA,
    DRIVER_SCHEMA,
    COMPLETE_POLICY_SCHEMA
)

from .prompts import (
    CLASSIFY_POLICY_PROMPT,
    get_extract_all_prompt
)

# --- HELPERS ---

@lru_cache(maxsize=16)
def get_cached_registry_json(policy_type: str) -> str:
    """Cached generation of the registry JSON string to save tokens/CPU."""
    filtered_registry = {}
    constraints = POLICY_TYPE_CONSTRAINTS.get(policy_type)
    
    # We always minify to save tokens (f=family, s=structure, l=allowed_limits)
    def _minify(entry):
        return {
            "f": entry["family"],
            "s": entry["limit_structure"],
            "l": entry.get("allowed_limits", [])
        }

    if constraints:
            allowed = set(constraints.get("allowed_families", []))
            forbidden = set(constraints.get("forbidden_codes", []))
            for code, entry in COVERAGE_REGISTRY.items():
                if entry["family"] in allowed and code not in forbidden:
                    filtered_registry[code] = _minify(entry)
    else:
            for code, entry in COVERAGE_REGISTRY.items():
                filtered_registry[code] = _minify(entry)
                
    return json.dumps(filtered_registry, separators=(',', ':')) # Compact JSON

# --- CONFIGURATION ---
ROUTING_MODEL = "gemini-2.5-flash"
EXTRACTION_MODEL = "gemini-2.5-flash"
CACHE_VERSION = "v11_turbo" # Bumped for new Architecture + Short Doc Strategy


# --- STATE MANAGEMENT ---

@dataclass
class ExtractionContext:
    """Holds the state for a single extraction request."""
    file_bytes: bytes
    file_hash: str
    
    classification: dict = field(default_factory=dict)
    extracted_data: dict = field(default_factory=dict) # Raw API responses
    
    # Normalized Results
    final_policy: dict = field(default_factory=dict)
    final_coverages: list = field(default_factory=list)
    final_vehicles: list = field(default_factory=list)
    final_drivers: list = field(default_factory=list)
    
    usage_metadata: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    carrier_hints: str = ""

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
        self.kb = CarrierKnowledgeBase()




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
        
        # 2. Local Cache Check
        cache_system = ExtractionCache()
        cached_result = cache_system.get(ctx.file_hash)
        if cached_result and not force_refresh:
            return cached_result, {"source": "cache", "cost": 0}, None
        
        uploaded_file = None
        
        try:
            # 3. Upload to Gemini File API
            logger.info("Uploading to Gemini File API...")
            if status_callback: status_callback(" Reading the Document...")
            
            uploaded_file = self._upload_to_gemini(file_bytes)
            logger.info(f"File uploaded: {uploaded_file.name}")
            
        except Exception as e:
            return None, None, f"Initialization Error: {str(e)}"
            
        # 4. Extraction (Universal One-Shot)
        active_cache = None
        try:
            # --- CACHE CREATION (Always attempt for One-Shot) ---
            if uploaded_file:
                if status_callback: status_callback(" Creating Context Cache...")
                active_cache = self._create_cache(uploaded_file)
            
            # Use Cache Name if valid, otherwise fallback to uploaded_file object
            final_content_reference = active_cache.name if active_cache else uploaded_file

            if status_callback: status_callback(" 🧠 Performing Deep Extraction (Universal One-Shot)...")
            
            # Generate Dynamic Registry Prompt (Full Registry for Universal Call)
            registry_json = get_cached_registry_json(None) 
            prompt = get_extract_all_prompt(registry_json)

            # --- SINGLE MEGA-CALL ---
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=COMPLETE_POLICY_SCHEMA
            )
            
            # If using cache, we pass the cache name in the config
            contents = [prompt]
            if active_cache:
                config.cached_content = active_cache.name
            else:
                # Fallback: Pass the file object directly if cache failed (e.g. small file)
                contents.insert(0, uploaded_file)

            response = self._call_gemini(
                model=EXTRACTION_MODEL,
                contents=contents, # Prompt + (Optional File if no cache)
                config=config,
                request_type="universal_one_shot"
            )

            raw_data = self._parse_json_response(response.text, ctx)
            
            # --- MAP TO CONTEXT ---
            ctx.classification = raw_data.get("classification", {})
            ctx.extracted_data["policy"] = raw_data.get("policy", {})
            ctx.extracted_data["coverages"] = {"coverages": raw_data.get("coverages", [])}
            ctx.extracted_data["vehicles"] = {"vehicles": raw_data.get("vehicles", [])} 
            ctx.extracted_data["drivers"] = {"drivers": raw_data.get("drivers", [])}
            
            logger.info(f"Policy Classified: {ctx.policy_type} ({ctx.confidence})")

            if ctx.policy_type == "unknown":
                return None, None, "Unknown Policy Type"
            
        except Exception as e:
            return None, None, f"Extraction Error: {str(e)}"
        
        finally:
            # Cleanup Cache explicitly if we finished
             if active_cache:
                try:
                    self.client.caches.delete(name=active_cache.name)
                    logger.debug("Deleted Cache context.")
                except:
                    pass
             
             # Cleanup File if it exists (and we aren't relying on it for a living cache)
             if uploaded_file:
                 try:
                     self.client.files.delete(name=uploaded_file.name)
                 except: pass
            


        # 6. Normalize & Validate
        final_result = self._assemble_result(ctx, processor)
        



        
        # 7. Cache Save
        # Only save if valid OR if we accept partials (user preference usually valid)
        # We save anyway but log it.
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

    def _create_cache(self, uploaded_file, ttl="300s"):
        """Creates a temporary context cache for this document."""
        try:
            cache = self.client.caches.create(
                model=EXTRACTION_MODEL,
                config=types.CreateCachedContentConfig(
                    display_name="insurance_extraction_ctx",
                    system_instruction="You are an expert insurance underwriter and data extraction specialist.",
                    contents=[uploaded_file],
                    ttl=ttl
                )
            )
            logger.info(f"CACHE CREATED: {cache.name} (TTL: {ttl})")
            return cache
        except Exception as e:
            logger.warning(f"Failed to create cache: {e}. Falling back to standard upload.")
            return None

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
