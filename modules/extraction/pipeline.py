from google import genai
from google.genai import types
import os
import json
import hashlib
import tempfile
import time

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any, Tuple
from functools import lru_cache

from core.logger import logger
from core.constants import DEFAULT_DAILY_BUDGET
from .pdf_ops import PdfProcessor
from utils.vehicle_utils import refine_vehicle_type
from utils.premium_audit import audit_premium_vs_fleet

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
from core.coverage_normalization import (
    apply_alias_resolution,
    apply_commercial_auto_audits,
    effective_stacked_um_limit,
    merge_autoliability_split_rows,
    normalize_limit_descriptors,
    enrich_statutory_policy_display,
    enrich_coverage_from_registry,
)
from core.document_taxonomy import DOCUMENT_TYPES
from core.variant_tracker import VariantTracker
from core.database import get_session, create_engine
from core.services import UsageService

from .knowledge_base import CarrierKnowledgeBase

from .schemas import (
    CLASSIFICATION_SCHEMA,
    DECLARATIONS_SCHEMA,
    COVERAGE_SCHEMA,
    VEHICLE_SCHEMA,
    DRIVER_SCHEMA,
    COMPLETE_POLICY_SCHEMA,
    COI_SUMMARY_SCHEMA,
)

from .prompts import (
    CLASSIFY_POLICY_PROMPT,
    get_extract_all_prompt,
    get_extract_coi_prompt,
)

POLICY_TYPE_ENUM: Tuple[str, ...] = tuple(
    CLASSIFICATION_SCHEMA["properties"]["policy_type"]["enum"]
)


def extraction_result_cache_scope(user_policy_type: Optional[str]) -> str:
    """Scope segment for local JSON extraction cache (auto vs manual selection)."""
    if not user_policy_type:
        return "auto"
    return f"manual_{user_policy_type}"


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

ROUTING_MODEL = "gemini-2.5-flash"
EXTRACTION_MODEL = "gemini-2.5-flash"


def _compute_cache_version() -> str:
    content = (
        CLASSIFY_POLICY_PROMPT
        + get_extract_coi_prompt()
        + get_extract_all_prompt("__REGISTRY_PLACEHOLDER__")
        + json.dumps(COMPLETE_POLICY_SCHEMA, sort_keys=True)
        + json.dumps(COI_SUMMARY_SCHEMA, sort_keys=True)
    )
    return hashlib.md5(content.encode()).hexdigest()[:8]


CACHE_VERSION = f"v_auto_{_compute_cache_version()}"
logger.info(f"Extraction cache version: {CACHE_VERSION}")

NON_EXTRACTABLE_MESSAGES = {
    "quote": "This document is a quote/proposal and is not extractable as bound coverage.",
    "application": "This document is an application and is not extractable as active coverage.",
    "endorsement": "This endorsement requires a parent policy context and is skipped in Phase 3.",
}


@dataclass
class ExtractionContext:
    """Holds the state for a single extraction request."""
    file_bytes: bytes
    file_hash: str
    user_selected_policy_type: Optional[str] = None
    classification_warnings: list = field(default_factory=list)

    classification: dict = field(default_factory=dict)
    extracted_data: dict = field(default_factory=dict) # Raw API responses
    
    final_policy: dict = field(default_factory=dict)
    final_coverages: list = field(default_factory=list)
    final_vehicles: list = field(default_factory=list)
    final_drivers: list = field(default_factory=list)
    
    usage_metadata: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    carrier_hints: str = ""
    variant_status: str = "known"

    @property
    def policy_type(self) -> str:
        return self.classification.get('policy_type', 'unknown')
        
    @property
    def confidence(self) -> str:
        return self.classification.get('confidence', 'unknown')


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

    @staticmethod
    def _result_storage_key(file_hash: str, cache_scope: str) -> str:
        """Filesystem-safe key for cached extraction JSON (scope avoids cross-mode hits)."""
        return f"{CACHE_VERSION}_{cache_scope}_{file_hash}"

    def get(self, file_hash: str, cache_scope: str = "auto") -> Optional[dict]:
        key = self._result_storage_key(file_hash, cache_scope)
        try:
            cache_path = os.path.join(self.cache_dir, f"{key}.json")
            if os.path.exists(cache_path):
                with open(cache_path, 'r') as f:
                    logger.info(f"CACHE HIT: {key}")
                    return json.load(f)
        except Exception as e:
            logger.error(f"Cache Read Error: {e}")
        return None

    def save(self, file_hash: str, data: dict, cache_scope: str = "auto"):
        key = self._result_storage_key(file_hash, cache_scope)
        try:
            cache_path = os.path.join(self.cache_dir, f"{key}.json")
            with open(cache_path, 'w') as f:
                json.dump(data, f, indent=2)
            logger.debug(f"CACHE SAVED: {key}")
        except Exception as e:
            logger.error(f"Cache Write Error: {e}")

    def get_gemini_cache_meta(self, file_hash: str) -> Optional[dict]:
        """Returns persisted Gemini cache metadata for this file hash, if any."""
        try:
            with open(self.index_file, "r") as f:
                index = json.load(f)
            return index.get(f"{CACHE_VERSION}_{file_hash}")
        except Exception as e:
            logger.debug(f"Gemini cache meta read error: {e}")
            return None

    def save_gemini_cache_meta(self, file_hash: str, cache_name: str, expire_time: Optional[str], model: str):
        """Persists Gemini cache metadata so repeated runs can reuse active cache."""
        try:
            with open(self.index_file, "r") as f:
                index = json.load(f)
            index[f"{CACHE_VERSION}_{file_hash}"] = {
                "cache_name": cache_name,
                "expire_time": expire_time,
                "model": model,
            }
            with open(self.index_file, "w") as f:
                json.dump(index, f, indent=2)
        except Exception as e:
            logger.debug(f"Gemini cache meta write error: {e}")

    def mark_non_cacheable(self, file_hash: str, reason: str):
        """Remember that this hash should skip cache-create attempts."""
        try:
            with open(self.index_file, "r") as f:
                index = json.load(f)
            key = f"{CACHE_VERSION}_{file_hash}_cacheability"
            index[key] = {"non_cacheable": True, "reason": reason}
            with open(self.index_file, "w") as f:
                json.dump(index, f, indent=2)
        except Exception as e:
            logger.debug(f"Non-cacheable marker write error: {e}")

    def is_marked_non_cacheable(self, file_hash: str) -> bool:
        try:
            with open(self.index_file, "r") as f:
                index = json.load(f)
            key = f"{CACHE_VERSION}_{file_hash}_cacheability"
            return bool(index.get(key, {}).get("non_cacheable"))
        except Exception:
            return False

class GeminiExtractionPipeline:
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
        self.engine = create_engine("sqlite:///insurance_data.db")
        self.session = get_session(self.engine)
        self.usage_service = UsageService(self.session)
        self.kb = CarrierKnowledgeBase()




    def run(
        self,
        file_bytes: bytes,
        status_callback=None,
        force_refresh: bool = False,
        user_policy_type: Optional[str] = None,
    ) -> tuple[Optional[dict], dict, Optional[str]]:
        """
        Main Entry Point.
        Returns: (data, usage, error_message)
        When user_policy_type is set, skips the classifier call and scopes the registry to that type.
        """
        if user_policy_type is not None and user_policy_type not in POLICY_TYPE_ENUM:
            return None, {"source": "error", "cost": 0}, "Invalid policy type"

        processor = PdfProcessor(file_bytes)
        cache_scope = extraction_result_cache_scope(user_policy_type)
        ctx = ExtractionContext(
            file_bytes=file_bytes,
            file_hash=processor.get_hash(),
            user_selected_policy_type=user_policy_type,
        )
        if user_policy_type:
            ctx.usage_metadata["extraction_mode"] = "manual"
        else:
            ctx.usage_metadata["extraction_mode"] = "auto"

        cache_system = ExtractionCache()
        cached_result = cache_system.get(ctx.file_hash, cache_scope)
        if cached_result and not force_refresh:
            if isinstance(cached_result, dict):
                cached_result.setdefault("variant_status", "known")
            return cached_result, {"source": "cache", "cost": 0}, None

        uploaded_file = None
        active_cache = None
        try:
            if status_callback:
                status_callback(" Checking Context Cache...")
            active_cache = self._get_reusable_cache(ctx.file_hash, cache_system)

            if not active_cache:
                logger.info("Uploading to Gemini File API...")
                if status_callback:
                    status_callback(" Reading the Document...")
                uploaded_file = self._upload_to_gemini(file_bytes)
                logger.info(f"File uploaded: {uploaded_file.name}")

                if status_callback:
                    status_callback(" Creating Context Cache...")
                if not cache_system.is_marked_non_cacheable(ctx.file_hash) and self._should_attempt_cache(processor):
                    active_cache = self._create_cache(uploaded_file)
                    if active_cache:
                        cache_system.save_gemini_cache_meta(
                            file_hash=ctx.file_hash,
                            cache_name=active_cache.name,
                            expire_time=getattr(active_cache, "expire_time", None),
                            model=EXTRACTION_MODEL,
                        )
                else:
                    cache_system.mark_non_cacheable(ctx.file_hash, "document_too_small_for_cache")
                    logger.info("Skipping cache create (small/non-cacheable document).")

            if user_policy_type:
                if status_callback:
                    status_callback(" Using user-selected policy type...")
                ctx.classification = {
                    "document_type": "unknown",
                    "policy_type": user_policy_type,
                    "confidence": "high",
                    "signals": ["user_selected"],
                }
                scoped_policy_type = user_policy_type
                logger.info(f"User-selected policy type: {user_policy_type} (classifier skipped)")
            else:
                if status_callback:
                    status_callback(" Classifying Policy Type...")
                ctx.classification = self._classify_policy_input(active_cache, uploaded_file)
                logger.info(f"Routing classification: {ctx.policy_type} ({ctx.confidence})")

                # Deterministic pre-pass is advisory only; classification remains the primary scope signal.
                policy_hint = self._infer_policy_type_hint(processor)
                scoped_policy_type = None
                if ctx.policy_type != "unknown" and ctx.confidence in {"high", "medium"}:
                    scoped_policy_type = ctx.policy_type
                elif policy_hint in {"personal_auto", "commercial_auto"}:
                    # Only trust deterministic hints for strong auto signals.
                    scoped_policy_type = policy_hint
                elif policy_hint in {"general_liability", "bop"} and (
                    ctx.policy_type == "unknown" or ctx.confidence == "low"
                ):
                    scoped_policy_type = policy_hint

            doc_type = ctx.classification.get("document_type", "unknown")
            doc_meta = DOCUMENT_TYPES.get(doc_type, DOCUMENT_TYPES["unknown"])
            extraction_goal = doc_meta.get("extraction_goal")
            if doc_meta.get("extractable") is False:
                ctx.variant_status = self._track_variant(processor, ctx)
                non_extractable_result = {
                    "document_type": doc_type,
                    "extractable": False,
                    "message": NON_EXTRACTABLE_MESSAGES.get(
                        doc_type,
                        f"{doc_meta.get('display', 'This document type')} is not extractable.",
                    ),
                    "classification": ctx.classification,
                    "variant_status": ctx.variant_status,
                }
                return non_extractable_result, ctx.usage_metadata, None

            if status_callback:
                status_callback(" PerformingExtraction (Universal One-Shot)...")
            registry_json = get_cached_registry_json(scoped_policy_type)
            early_text_lower = processor.extract_text([0, 1]).lower()
            matched_carrier = self._carrier_name_from_early_text(early_text_lower)
            carrier_hint_block = (
                self.kb.get_hints_capped(matched_carrier, max_bullets=2)
                if matched_carrier
                else ""
            )
            ctx.carrier_hints = carrier_hint_block
            if extraction_goal == "coi_summary":
                logger.info("Document taxonomy route: coi_summary")
                response = self._run_coi_extraction(
                    active_cache=active_cache,
                    uploaded_file=uploaded_file,
                    user_policy_type=user_policy_type,
                    carrier_hint_block=carrier_hint_block,
                )
            else:
                response = self._run_full_extraction(
                    active_cache=active_cache,
                    uploaded_file=uploaded_file,
                    user_policy_type=user_policy_type,
                    carrier_hint_block=carrier_hint_block,
                    registry_json=registry_json,
                )
            ctx.usage_metadata["llm_retries"] = ctx.usage_metadata.get("llm_retries", 0) + int(getattr(self, "_last_call_retries", 0))
            if response.usage_metadata:
                ctx.usage_metadata["prompt_tokens"] = response.usage_metadata.prompt_token_count or 0
                ctx.usage_metadata["cached_content_tokens"] = response.usage_metadata.cached_content_token_count or 0
                ctx.usage_metadata["output_tokens"] = response.usage_metadata.candidates_token_count or 0
                ctx.usage_metadata["total_tokens"] = response.usage_metadata.total_token_count or 0

            raw_data = self._parse_json_response(response.text, ctx)
            if not raw_data:
                return None, ctx.usage_metadata, "Extraction Parse Error"
            if extraction_goal == "coi_summary":
                raw_data = self._normalize_coi_result(raw_data, ctx.classification)

            extracted_classification = raw_data.get("classification", {}) or {}
            if user_policy_type:
                model_pt = extracted_classification.get("policy_type")
                if (
                    model_pt
                    and model_pt != user_policy_type
                    and model_pt != "unknown"
                ):
                    ctx.classification_warnings.append(
                        f"Model classification ({model_pt}) differs from user-selected ({user_policy_type})."
                    )
                ctx.classification = {
                    "document_type": extracted_classification.get("document_type", "unknown"),
                    "policy_type": user_policy_type,
                    "confidence": "high",
                    "signals": ["user_selected"],
                }
            elif extracted_classification and extracted_classification.get("policy_type"):
                ctx.classification = extracted_classification
            ctx.extracted_data["policy"] = raw_data.get("policy", {})
            ctx.extracted_data["compliance"] = raw_data.get("compliance") or {}
            ctx.extracted_data["coverages"] = {"coverages": raw_data.get("coverages", [])}
            vehicle_rows = raw_data.get("vehicles")
            driver_rows = raw_data.get("drivers")
            ctx.extracted_data["vehicles"] = {"vehicles": vehicle_rows if isinstance(vehicle_rows, list) else []}
            ctx.extracted_data["drivers"] = {"drivers": driver_rows if isinstance(driver_rows, list) else []}
            ctx.usage_metadata["policy_data_source"] = (
                "coi_summary" if extraction_goal == "coi_summary" else "full_policy"
            )
            
            logger.info(f"Policy Classified: {ctx.policy_type} ({ctx.confidence})")

            if ctx.policy_type == "unknown":
                return None, None, "Unknown Policy Type"
            ctx.variant_status = self._track_variant(processor, ctx)
            
        except Exception as e:
            return None, None, f"Extraction Error: {str(e)}"
        
        finally:
             if uploaded_file:
                 try:
                     self.client.files.delete(name=uploaded_file.name)
                 except: pass
            


        final_result = self._assemble_result(ctx, processor)
        final_result["policy_data_source"] = ctx.usage_metadata.get("policy_data_source", "full_policy")
        final_result["variant_status"] = ctx.variant_status
        



        
        try:
            cache_system.save(ctx.file_hash, final_result, cache_scope)
        except Exception as e:
            logger.error(f"Failed to save cache: {e}")

        ctx.usage_metadata["source"] = "api"
        return final_result, ctx.usage_metadata, None

    def _track_variant(self, processor: PdfProcessor, ctx: ExtractionContext) -> str:
        try:
            tracker = VariantTracker()
            variant_result = tracker.check_and_record(
                fingerprint=ctx.file_hash,
                carrier_name=ctx.classification.get("carrier_name", "unknown"),
                document_type=ctx.classification.get("document_type", "unknown"),
                policy_type=ctx.classification.get("policy_type", "unknown"),
                page_count=processor.get_page_count(),
                file_hash=ctx.file_hash,
            )
            return variant_result.get("status", "known")
        except Exception as exc:
            logger.warning(f"VARIANT TRACKER: unable to record variant: {exc}")
            return "known"

    def _get_reusable_cache(self, file_hash: str, cache_system: ExtractionCache):
        """Attempts to reuse a live cache for the same file hash to save tokens and latency."""
        meta = cache_system.get_gemini_cache_meta(file_hash)
        if not meta:
            return None
        if meta.get("model") != EXTRACTION_MODEL:
            return None

        cache_name = meta.get("cache_name")
        expire_time_raw = meta.get("expire_time")
        if not cache_name:
            return None

        if expire_time_raw:
            try:
                expire_time = datetime.fromisoformat(expire_time_raw.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) >= expire_time:
                    return None
            except Exception:
                # Fall back to API check if parsing fails.
                pass

        try:
            cache = self.client.caches.get(name=cache_name)
            logger.info(f"CACHE REUSED: {cache_name}")
            return cache
        except Exception as e:
            logger.info(f"Cache reuse miss: {e}")
            return None

    def _should_attempt_cache(self, processor: PdfProcessor) -> bool:
        """
        Cache-create guard for tiny docs.
        Empirical threshold to reduce repeated INVALID_ARGUMENT cache-create calls.
        """
        text = processor.extract_text([0, 1])
        return len(text.strip()) >= 1200

    def _carrier_name_from_early_text(self, text_lower: str) -> str:
        """Match longest KB carrier key contained in early-page text (deterministic)."""
        if not text_lower.strip():
            return ""
        names = sorted(self.kb.hints.keys(), key=len, reverse=True)
        for name in names:
            if name.lower() in text_lower:
                return name
        return ""

    def _infer_policy_type_hint(self, processor: PdfProcessor) -> Optional[str]:
        """
        Deterministic pre-pass: infer likely policy type from early-page text.
        Keeps call count low while still enabling scoped registry.
        """
        text = processor.extract_text([0, 1]).lower()
        if not text:
            return None
        if "motor truck cargo" in text or "motor carrier cargo" in text:
            return "motor_truck_cargo"
        if "commercial auto" in text or "motor carrier" in text:
            return "commercial_auto"
        if "cargo" in text:
            return "commercial_auto"
        if "personal auto" in text or "personal automobile" in text:
            return "personal_auto"
        if (
            "general liability coverage part" in text
            or "general liability coverage form" in text
            or "commercial general liability" in text
            or "cgl declarations" in text
        ):
            return "general_liability"
        if (
            "businessowners policy" in text
            or "business owners policy" in text
            or "businessowner policy" in text
        ):
            return "bop"
        if " bop " in f" {text} ":
            return "bop"
        if "umbrella" in text:
            return "umbrella"
        if "cargo" in text and "auto" in text:
            return "commercial_auto"
        return None



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

    def _is_retryable_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        markers = ["429", "rate limit", "resource exhausted", "timeout", "temporarily unavailable", "internal error", "503", "500"]
        return any(m in msg for m in markers)

    def _call_gemini(self, model: str, contents: list, config: types.GenerateContentConfig, request_type: str = "extraction"):
        """Centralized wrapper to enforce daily budget and log usage."""
        if self.usage_service.is_over_budget(daily_limit=DEFAULT_DAILY_BUDGET):
             raise Exception(
                 f"STOPS: API Daily Quota Exceeded (${DEFAULT_DAILY_BUDGET}). Processing halted to prevent billing."
             )
        
        config.temperature = 0.0
        
        max_retries = 2
        attempt = 0
        response = None
        started_at = time.perf_counter()
        while attempt <= max_retries:
            try:
                response = self.client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config
                )
                break
            except Exception as e:
                if attempt >= max_retries or not self._is_retryable_error(e):
                    raise
                sleep_s = 1.5 ** attempt
                logger.warning(f"Retrying LLM call ({request_type}) attempt={attempt + 1}: {e}")
                time.sleep(sleep_s)
                attempt += 1
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        
        if response.usage_metadata:
            cached_tokens = response.usage_metadata.cached_content_token_count or 0
            logger.info(
                f"LLM usage | model={model} type={request_type} "
                f"input={response.usage_metadata.prompt_token_count} "
                f"cached={cached_tokens} output={response.usage_metadata.candidates_token_count} "
                f"latency_ms={elapsed_ms} retries={attempt}"
            )
            self.usage_service.log_usage(
                model_name=model,
                input_tokens=response.usage_metadata.prompt_token_count,
                output_tokens=response.usage_metadata.candidates_token_count,
                request_type=request_type
            )
        self._last_call_retries = attempt
            
        return response

    def _classify_policy(self, uploaded_file) -> dict:
        response = self._call_gemini(
            model=ROUTING_MODEL,
            contents=[uploaded_file, CLASSIFY_POLICY_PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=CLASSIFICATION_SCHEMA,
                thinking_config=types.ThinkingConfig(thinking_budget=0)
            ),
            request_type="classification"
        )
        return self._parse_json_response(response.text)

    def _classify_policy_input(self, active_cache, uploaded_file) -> dict:
        """Runs a lightweight classification pass using cache when available."""
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=CLASSIFICATION_SCHEMA,
            thinking_config=types.ThinkingConfig(thinking_budget=0)
        )
        contents = [CLASSIFY_POLICY_PROMPT]
        if active_cache:
            config.cached_content = active_cache.name
        elif uploaded_file:
            contents.insert(0, uploaded_file)

        response = self._call_gemini(
            model=ROUTING_MODEL,
            contents=contents,
            config=config,
            request_type="classification",
        )
        return self._parse_json_response(response.text)

    def _run_full_extraction(
        self,
        active_cache,
        uploaded_file,
        user_policy_type: Optional[str],
        carrier_hint_block: str,
        registry_json: str,
    ):
        prompt = get_extract_all_prompt(
            registry_json,
            user_policy_type=user_policy_type,
            carrier_hints_suffix=carrier_hint_block,
        )
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=COMPLETE_POLICY_SCHEMA,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        contents = [prompt]
        if active_cache:
            config.cached_content = active_cache.name
        else:
            contents.insert(0, uploaded_file)
        return self._call_gemini(
            model=EXTRACTION_MODEL,
            contents=contents,
            config=config,
            request_type="universal_one_shot",
        )

    def _run_coi_extraction(
        self,
        active_cache,
        uploaded_file,
        user_policy_type: Optional[str],
        carrier_hint_block: str,
    ):
        prompt = get_extract_coi_prompt(
            user_policy_type=user_policy_type,
            carrier_hints_suffix=carrier_hint_block,
        )
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=COI_SUMMARY_SCHEMA,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        contents = [prompt]
        if active_cache:
            config.cached_content = active_cache.name
        else:
            contents.insert(0, uploaded_file)
        return self._call_gemini(
            model=EXTRACTION_MODEL,
            contents=contents,
            config=config,
            request_type="coi_summary",
        )

    def _normalize_coi_result(self, raw_data: dict, fallback_classification: dict) -> dict:
        policies = raw_data.get("policies") or []
        policy_rows = [p for p in policies if isinstance(p, dict)]

        def _clean_text(value):
            if value is None:
                return None
            if not isinstance(value, str):
                return value
            compact = " ".join(value.replace("\u200b", "").split()).strip()
            if not compact:
                return None
            if compact.lower() in {"null", "none", "n/a", "-"}:
                return None
            return compact

        def _pick_first_nonempty(key: str):
            for row in policy_rows:
                val = _clean_text(row.get(key))
                if val is not None:
                    return val
            return None

        aggregated_limits = {}
        for row in policy_rows:
            limits = row.get("limits") if isinstance(row.get("limits"), dict) else {}
            for limit_key, limit_val in limits.items():
                clean_limit = _clean_text(limit_val)
                if clean_limit is not None and aggregated_limits.get(limit_key) in (None, ""):
                    aggregated_limits[limit_key] = clean_limit

        classification = raw_data.get("classification") or fallback_classification or {}
        if "document_type" not in classification:
            classification["document_type"] = "certificate_of_insurance"

        normalized_policy = {
            "carrier_name": _pick_first_nonempty("carrier_name"),
            "naic_number": _pick_first_nonempty("naic_number"),
            "policy_number": _pick_first_nonempty("policy_number"),
            "effective_date": _pick_first_nonempty("effective_date"),
            "expiration_date": _pick_first_nonempty("expiration_date"),
            "insured_name": _clean_text((raw_data.get("insured") or {}).get("name")),
            "insured_address": _clean_text((raw_data.get("insured") or {}).get("address")),
            "financial_responsibility_name": _clean_text((raw_data.get("producer") or {}).get("name")),
            "liability_limit": aggregated_limits.get("liability_limit"),
            "general_liability_limit": aggregated_limits.get("general_liability_limit"),
            "cargo_limit": aggregated_limits.get("cargo_limit"),
            "cargo_deductible": aggregated_limits.get("cargo_deductible"),
            "um_uim_limit": aggregated_limits.get("um_uim_limit"),
            "med_pay_limit": aggregated_limits.get("med_pay_limit"),
            "pip_limit": aggregated_limits.get("pip_limit"),
            "comp_deductible": aggregated_limits.get("comp_deductible"),
            "coll_deductible": aggregated_limits.get("coll_deductible"),
        }

        return {
            "classification": classification,
            "policy": normalized_policy,
            "compliance": {},
            "coverages": [],
            "vehicles": raw_data.get("vehicles") if isinstance(raw_data.get("vehicles"), list) else [],
            "drivers": raw_data.get("drivers") if isinstance(raw_data.get("drivers"), list) else [],
            "coi_summary": {
                "certificate_holder": raw_data.get("certificate_holder") or {},
                "insured": raw_data.get("insured") or {},
                "producer": raw_data.get("producer") or {},
                "policies": policies,
                "additional_insured_text": raw_data.get("additional_insured_text"),
                "cancellation_notice_days": raw_data.get("cancellation_notice_days"),
                "description_of_operations": raw_data.get("description_of_operations"),
            },
        }



    def _parse_json_response(self, text: str, ctx: Optional[ExtractionContext] = None) -> dict:
        """Centralized result parser to handle Gemini's list/dict inconsistency recursively."""
        try:
            data = json.loads(text)
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
            if ctx:
                ctx.errors.append(f"parse_error:{e}")
                ctx.usage_metadata["parse_error"] = str(e)
            return {}









    def _clean_coverage_zeros(self, coverages: list) -> list:
        """
        Gemini's structured output fills missing INTEGER fields with 0 instead of null.
        Since $0 limits and $0 deductibles don't exist in real insurance documents,
        we safely convert them to None so downstream logic (summaries, validation) works correctly.
        """
        LIMIT_KEYS = {"per_person", "per_accident", "per_occurrence", "combined_single_limit", "aggregate"}
        for c in coverages:
            if isinstance(c.get("limits"), dict):
                for k in LIMIT_KEYS:
                    if c["limits"].get(k) == 0:
                        c["limits"][k] = None
            if c.get("deductible") == 0:
                c["deductible"] = None
            if c.get("vehicle_vin") in ("null", ""):
                c["vehicle_vin"] = None
        return coverages

    def _assemble_result(self, ctx: ExtractionContext, processor: PdfProcessor) -> dict:
        
        comp = ctx.extracted_data.get("compliance") or {}
        pol_decl = ctx.extracted_data.get("policy", {}) or {}
        for k in ("mcs90_noted", "motor_carrier_id", "dot_number", "drive_other_car_note"):
            v = pol_decl.get(k)
            if v and not comp.get(k):
                comp = {**comp, k: v}
        final = {
            "policy": pol_decl,
            "compliance": comp,
            "coverages": [],
            "vehicles": [],
            "drivers": ctx.extracted_data.get("drivers", {}).get("drivers", []),
            "audits": {},
            "classification": ctx.classification,
            "page_dimensions": processor.get_dimensions(),
            "extraction_audit": {
                "errors": list(ctx.errors),
                "rejected_coverages": [],
                "classification_warnings": list(ctx.classification_warnings),
            }
        }
        if ctx.user_selected_policy_type:
            final["extraction_audit"]["user_selected_policy_type"] = ctx.user_selected_policy_type

        raw_vehs = ctx.extracted_data.get("vehicles", {}).get("vehicles", [])
        for v in raw_vehs:
            refined = refine_vehicle_type(
                year=v.get('year'),
                make=v.get('make'),
                model=v.get('model'),
                vin=v.get('vin'),
                extracted_type=v.get('type'),
                extracted_chassis=v.get('chassis'),
                extracted_body=v.get('body'),
                gvw=v.get('gvw')
            )
            v['type'] = refined['final_type']
            v['make'] = refined['make']
            v['model'] = refined['model']
            v['chassis'] = refined.get('chassis') or v.get('chassis')
            v['body'] = refined.get('body') or v.get('body')
            final["vehicles"].append(v)
        
        raw_covs = self._clean_coverage_zeros(
            ctx.extracted_data.get("coverages", {}).get("coverages", [])
        )
        raw_covs = apply_alias_resolution(raw_covs)
        raw_covs = normalize_limit_descriptors(raw_covs)
        raw_covs, liab_notes = merge_autoliability_split_rows(raw_covs)
        for ln in liab_notes:
            final["extraction_audit"].setdefault("liability_normalization", []).append(ln)
        cflags, cnotes = apply_commercial_auto_audits(final["vehicles"], ctx.policy_type)
        if cflags:
            final["extraction_audit"]["commercial_flags"] = cflags
        for note in cnotes:
            final["extraction_audit"].setdefault("ontology_notes", []).append(note)

        for c in raw_covs:
            c = enrich_coverage_from_registry(c)
            code = c.get("coverage_code")
            if not code:
                final["extraction_audit"]["rejected_coverages"].append(
                    {"coverage_code": None, "reason": "missing_coverage_code"}
                )
                continue
                
            if not is_coverage_allowed_for_policy_type(code, ctx.policy_type):
                final["extraction_audit"]["rejected_coverages"].append(
                    {"coverage_code": code, "reason": f"not_allowed_for_policy_type:{ctx.policy_type}"}
                )
                continue
            is_valid, msg = validate_coverage(c)
            if is_valid:
                final["coverages"].append(c)
            else:
                final["extraction_audit"]["rejected_coverages"].append(
                    {"coverage_code": code, "reason": msg}
                )


        self._apply_auto_liability_rules(final["coverages"], ctx.policy_type)
        if ctx.usage_metadata.get("policy_data_source") != "coi_summary":
            self._compute_summaries(final)
        enrich_statutory_policy_display(final)

        final["policy"]["has_full_collision"] = any(c.get("family") == "physical_damage" for c in final["coverages"])
        final["audits"]["premium"] = audit_premium_vs_fleet(
            premium_str=final["policy"].get("premium"),
            vehicle_count=len(final["vehicles"]),
            policy_type=ctx.policy_type,
        )


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
        raw_summary = summarize_auto_liability(final["coverages"])
        if raw_summary:
            final["policy"]["liability_limit"] = format_liability_limit(raw_summary)
            
        raw_gl = summarize_general_liability(final["coverages"])
        if raw_gl:
            final["policy"]["general_liability_limit"] = format_liability_limit(raw_gl)
            
        raw_cargo = summarize_cargo(final["coverages"])
        if raw_cargo:
             final["policy"]["cargo_limit"] = f"${raw_cargo['value']:,}"
             if raw_cargo.get("deductible"):
                  final["policy"]["cargo_deductible"] = str(raw_cargo["deductible"])
        
        covs = final["coverages"]
        
        final["policy"]["um_uim_limit"] = summarize_um_uim(covs)
        final["policy"]["med_pay_limit"] = summarize_med_pay(covs)
        final["policy"]["pip_limit"] = summarize_pip(covs)
        for c in covs:
            if c.get("family") in ("uninsured_motorist", "underinsured_motorist") and c.get("is_stacked"):
                eff = effective_stacked_um_limit(c)
                if eff is not None:
                    final["policy"]["um_stacked_effective_limit"] = str(eff)
                    break
        
        phys_dam = summarize_physical_damage(covs)
        if phys_dam:
            final["policy"]["comp_deductible"] = phys_dam.get("comp")
            final["policy"]["coll_deductible"] = phys_dam.get("coll")

        final["policy"]["has_auto_liability"] = any(c.get("family") == "auto_liability" for c in covs)
        final["policy"]["has_general_liability"] = any(c.get("family") == "general_liability" for c in covs)
        final["policy"]["has_full_collision"] = any(c.get("family") == "physical_damage" for c in covs)


def process_pdf(
    file_bytes,
    api_key,
    status_callback=None,
    force_refresh: bool = False,
    user_policy_type: Optional[str] = None,
):
    """
    Wrapper function that instantiates the Pipeline Class.
    Maintains compatibility with views/process_policies.py
    """
    pipeline = GeminiExtractionPipeline(api_key=api_key)
    return pipeline.run(
        file_bytes,
        status_callback,
        force_refresh=force_refresh,
        user_policy_type=user_policy_type,
    )