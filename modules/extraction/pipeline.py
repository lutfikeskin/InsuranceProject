import re
from google import genai
from google.genai import types
from typing import Optional

from core.logger import logger
from core.database import get_session, create_engine
from core.document_taxonomy import DOCUMENT_TYPES
from core.services import UsageService
from core.variant_tracker import VariantTracker

from .knowledge_base import CarrierKnowledgeBase
from .coverage_registry_minify import get_cached_registry_json
from .cache_version import CACHE_VERSION, POLICY_TYPE_ENUM
from .extraction_types import ExtractionContext, NON_EXTRACTABLE_MESSAGES
from .extraction_local_cache import (
    ExtractionCache,
    extraction_result_cache_scope,
)
from .extraction_response import (
    normalize_coi_result,
    normalize_endorsement_result,
    parse_json_response,
)
from .extraction_assembly import (
    apply_auto_liability_rules,
    assemble_extraction_result,
)
from .gemini_transport import (
    GeminiTransport,
    ROUTING_MODEL,
    EXTRACTION_MODEL,
)
from .pdf_ops import PdfProcessor

from .schemas import (
    CLASSIFICATION_SCHEMA,
    COMPLETE_POLICY_SCHEMA,
    COI_SUMMARY_SCHEMA,
    ENDORSEMENT_SCHEMA,
    build_complete_policy_schema,
)
from .prompts import (
    CLASSIFY_POLICY_PROMPT,
    get_extract_all_prompt,
    get_extract_coi_prompt,
    get_extract_endorsement_prompt,
)


class GeminiExtractionPipeline:
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
        self.engine = create_engine("sqlite:///insurance_data.db")
        self.session = get_session(self.engine)
        self.usage_service = UsageService(self.session)
        self.kb = CarrierKnowledgeBase()
        self._transport = GeminiTransport(self.client, self.usage_service)

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
        extraction_goal = None
        raw_data = None
        try:
            if status_callback:
                status_callback(" Checking Context Cache...")
            active_cache = self._transport.get_reusable_cache(ctx.file_hash, cache_system)

            if not active_cache:
                logger.info("Uploading to Gemini File API...")
                if status_callback:
                    status_callback(" Reading the Document...")
                uploaded_file = self._transport.upload_to_gemini(file_bytes)
                logger.info(f"File uploaded: {uploaded_file.name}")

                if status_callback:
                    status_callback(" Creating Context Cache...")
                if not cache_system.is_marked_non_cacheable(
                    ctx.file_hash
                ) and self._should_attempt_cache(processor):
                    active_cache = self._transport.create_cache(uploaded_file)
                    if active_cache:
                        cache_system.save_gemini_cache_meta(
                            file_hash=ctx.file_hash,
                            cache_name=active_cache.name,
                            expire_time=getattr(active_cache, "expire_time", None),
                            model=EXTRACTION_MODEL,
                        )
                else:
                    cache_system.mark_non_cacheable(
                        ctx.file_hash, "document_too_small_for_cache"
                    )
                    logger.info("Skipping cache create (small/non-cacheable document).")

            doc_type_hint = self._infer_document_type_hint(processor)
            policy_type_hint = self._infer_policy_type_hint(processor)

            if user_policy_type:
                # User manually pinned policy_type; trust the regex doc_type
                # hint when present so misuploaded COIs/endorsements still
                # route correctly. Default to declarations_page otherwise.
                detected_doc = doc_type_hint or "declarations_page"
                ctx.classification = {
                    "document_type": detected_doc,
                    "policy_type": user_policy_type,
                    "confidence": "high",
                    "signals": ["user_selected"]
                    + ([f"text_hint:{doc_type_hint}"] if doc_type_hint else []),
                }
                scoped_policy_type = user_policy_type
                logger.info(
                    "User-selected policy type: "
                    f"{user_policy_type}; classifier skipped "
                    f"(document_type={detected_doc}, source={'text_hint' if doc_type_hint else 'default'})"
                )
            elif doc_type_hint and policy_type_hint:
                # Auto mode but both regex hints are confident; skip the
                # standalone LLM classifier. Combined extraction call still
                # emits its own classification block and may refine these.
                ctx.classification = {
                    "document_type": doc_type_hint,
                    "policy_type": policy_type_hint,
                    "confidence": "high",
                    "signals": ["text_hint"],
                }
                scoped_policy_type = policy_type_hint
                logger.info(
                    "Classifier skipped via text hints: "
                    f"document_type={doc_type_hint}, policy_type={policy_type_hint}"
                )
            else:
                if status_callback:
                    status_callback(" Classifying Policy Type...")
                ctx.classification = self._classify_policy_input(
                    active_cache, uploaded_file
                )
                logger.info(
                    f"Routing classification: {ctx.policy_type} ({ctx.confidence})"
                )

                scoped_policy_type = None
                if ctx.policy_type != "unknown" and ctx.confidence in {"high", "medium"}:
                    scoped_policy_type = ctx.policy_type
                elif policy_type_hint in {"personal_auto", "commercial_auto"}:
                    scoped_policy_type = policy_type_hint
                elif policy_type_hint in {"general_liability", "bop"} and (
                    ctx.policy_type == "unknown" or ctx.confidence == "low"
                ):
                    scoped_policy_type = policy_type_hint

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
            unreliable_fields: list[str] = []
            if matched_carrier and extraction_goal == "full_policy":
                try:
                    unreliable_rows = self.kb.get_unreliable_fields(
                        carrier_name=matched_carrier,
                        document_type=doc_type,
                        policy_type=scoped_policy_type or ctx.policy_type,
                        threshold=CarrierKnowledgeBase.UNRELIABLE_RATIO_THRESHOLD,
                    )
                    unreliable_fields = [
                        row.get("field")
                        for row in unreliable_rows
                        if isinstance(row, dict) and row.get("field")
                    ]
                except Exception as exc:
                    logger.warning(f"Unable to load unreliable field hints: {exc}")
            if extraction_goal == "coi_summary":
                logger.info("Document taxonomy route: coi_summary")
                response = self._run_coi_extraction(
                    active_cache=active_cache,
                    uploaded_file=uploaded_file,
                    user_policy_type=user_policy_type,
                    carrier_hint_block=carrier_hint_block,
                )
            elif extraction_goal == "endorsement_summary":
                logger.info("Document taxonomy route: endorsement_summary")
                response = self._run_endorsement_extraction(
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
                    scoped_policy_type=scoped_policy_type,
                    carrier_hint_block=carrier_hint_block,
                    registry_json=registry_json,
                    unreliable_fields=unreliable_fields,
                )
            ctx.usage_metadata["llm_retries"] = ctx.usage_metadata.get(
                "llm_retries", 0
            ) + int(getattr(self._transport, "_last_call_retries", 0))
            if response.usage_metadata:
                ctx.usage_metadata["prompt_tokens"] = (
                    response.usage_metadata.prompt_token_count or 0
                )
                ctx.usage_metadata["cached_content_tokens"] = (
                    response.usage_metadata.cached_content_token_count or 0
                )
                ctx.usage_metadata["output_tokens"] = (
                    response.usage_metadata.candidates_token_count or 0
                )
                ctx.usage_metadata["total_tokens"] = (
                    response.usage_metadata.total_token_count or 0
                )

            raw_data = parse_json_response(response.text, ctx)
            if not raw_data:
                return None, ctx.usage_metadata, "Extraction Parse Error"
            if extraction_goal == "coi_summary":
                raw_data = normalize_coi_result(raw_data, ctx.classification)
            elif extraction_goal == "endorsement_summary":
                raw_data = normalize_endorsement_result(
                    raw_data, ctx.classification, ctx.file_hash
                )

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
                    "document_type": (
                        extracted_classification.get("document_type")
                        or ctx.classification.get("document_type", "unknown")
                    ),
                    "policy_type": user_policy_type,
                    "confidence": "high",
                    "signals": ctx.classification.get("signals", ["user_selected"]),
                }
            elif extracted_classification and extracted_classification.get("policy_type"):
                ctx.classification = extracted_classification
            if extraction_goal == "endorsement_summary":
                ctx.usage_metadata["policy_data_source"] = "endorsement_summary"
            else:
                ctx.extracted_data["policy"] = raw_data.get("policy", {})
                ctx.extracted_data["compliance"] = raw_data.get("compliance") or {}
                ctx.extracted_data["coverages"] = {
                    "coverages": raw_data.get("coverages", [])
                }
                vehicle_rows = raw_data.get("vehicles")
                driver_rows = raw_data.get("drivers")
                ctx.extracted_data["vehicles"] = {
                    "vehicles": vehicle_rows if isinstance(vehicle_rows, list) else []
                }
                ctx.extracted_data["drivers"] = {
                    "drivers": driver_rows if isinstance(driver_rows, list) else []
                }
                ctx.usage_metadata["policy_data_source"] = (
                    "coi_summary" if extraction_goal == "coi_summary" else "full_policy"
                )

            logger.info(f"Policy Classified: {ctx.policy_type} ({ctx.confidence})")

            if extraction_goal != "endorsement_summary" and ctx.policy_type == "unknown":
                return None, None, "Unknown Policy Type"
            ctx.variant_status = self._track_variant(processor, ctx)

        except Exception as e:
            return None, None, f"Extraction Error: {str(e)}"

        finally:
            if uploaded_file:
                try:
                    self.client.files.delete(name=uploaded_file.name)
                except Exception:
                    pass

        if extraction_goal == "endorsement_summary":
            final_result = {
                "classification": ctx.classification,
                "endorsement": raw_data.get("endorsement", {}),
                "policy_data_source": "endorsement_summary",
                "variant_status": ctx.variant_status,
            }
        else:
            final_result = assemble_extraction_result(ctx, processor)
            final_result["policy_data_source"] = ctx.usage_metadata.get(
                "policy_data_source", "full_policy"
            )
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
        if (
            "personal auto" in text
            or "personal automobile" in text
            or "private passenger auto" in text
        ):
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
        if "your car" in text and (
            "automobile policy" in text or "automobile insurance" in text
        ):
            return "personal_auto"
        return None

    _ENDORSEMENT_FORM_RE = re.compile(
        r"\b(ca|cg|cp|bp|il|gl|um|ue|ur|mp|ho)\s*\d{2}\s*\d{2}\b"
    )

    def _infer_document_type_hint(self, processor: PdfProcessor) -> Optional[str]:
        """
        Deterministic pre-pass: infer document_type from early-page text.

        Returns one of declarations_page, renewal_declarations,
        certificate_of_insurance, memorandum, endorsement, quote, application,
        or None when ambiguous (multiple competing signals).
        Conservative: only returns a value when the cue is unambiguous.
        """
        text = processor.extract_text([0, 1]).lower()
        if not text:
            return None

        matches: list[str] = []

        if "memorandum of insurance" in text:
            matches.append("memorandum")
        if (
            "this certificate is issued as a matter of information" in text
            or "certificate of liability insurance" in text
            or ("acord" in text and re.search(r"\bacord\s*25\b", text))
            or "certificate holder" in text
        ):
            matches.append("certificate_of_insurance")
        if (
            "this is not a binder" in text
            or "this is a quote" in text
            or "quotation" in text
            or "indication of coverage" in text
        ):
            matches.append("quote")
        if "application for insurance" in text or "applicant signature" in text:
            matches.append("application")

        has_dec_marker = (
            "declarations page" in text
            or "policy declarations" in text
            or "automobile policy declarations" in text
            or "auto policy declarations" in text
        )
        has_renewal_marker = "renewal" in text and has_dec_marker
        has_endorsement_marker = bool(
            "endorsement" in text and self._ENDORSEMENT_FORM_RE.search(text)
        )

        if has_renewal_marker:
            matches.append("renewal_declarations")
        elif has_dec_marker:
            matches.append("declarations_page")

        if has_endorsement_marker and not has_dec_marker:
            matches.append("endorsement")

        matches = list(dict.fromkeys(matches))
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]
        if set(matches) == {"declarations_page", "renewal_declarations"}:
            return "renewal_declarations"
        return None

    def _classify_policy_input(self, active_cache, uploaded_file) -> dict:
        """Runs a lightweight classification pass using cache when available."""
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=CLASSIFICATION_SCHEMA,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        contents = [CLASSIFY_POLICY_PROMPT]
        if active_cache:
            config.cached_content = active_cache.name
        elif uploaded_file:
            contents.insert(0, uploaded_file)

        response = self._transport.call_gemini(
            model=ROUTING_MODEL,
            contents=contents,
            config=config,
            request_type="classification",
        )
        return parse_json_response(response.text)

    @staticmethod
    def _classification_with_user_policy_type(
        route_classification: dict, user_policy_type: str
    ) -> dict:
        """Preserve detected document_type while honoring manual policy_type selection."""
        route_classification = route_classification or {}
        route_signals = route_classification.get("signals") or []
        if not isinstance(route_signals, list):
            route_signals = [str(route_signals)]
        signals = ["user_selected"]
        for signal in route_signals:
            if signal and signal not in signals and len(signals) < 3:
                signals.append(signal)
        return {
            "document_type": route_classification.get("document_type", "unknown"),
            "policy_type": user_policy_type,
            "confidence": "high",
            "signals": signals,
        }

    def _run_full_extraction(
        self,
        active_cache,
        uploaded_file,
        user_policy_type: Optional[str],
        scoped_policy_type: Optional[str],
        carrier_hint_block: str,
        registry_json: str,
        unreliable_fields: Optional[list[str]] = None,
    ):
        prompt = get_extract_all_prompt(
            registry_json,
            user_policy_type=user_policy_type,
            scoped_policy_type=scoped_policy_type,
            carrier_hints_suffix=carrier_hint_block,
            unreliable_fields=unreliable_fields,
        )
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=build_complete_policy_schema(scoped_policy_type),
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        contents = [prompt]
        if active_cache:
            config.cached_content = active_cache.name
        else:
            contents.insert(0, uploaded_file)
        return self._transport.call_gemini(
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
        return self._transport.call_gemini(
            model=EXTRACTION_MODEL,
            contents=contents,
            config=config,
            request_type="coi_summary",
        )

    def _run_endorsement_extraction(
        self,
        active_cache,
        uploaded_file,
        user_policy_type: Optional[str],
        carrier_hint_block: str,
    ):
        prompt = get_extract_endorsement_prompt(
            user_policy_type=user_policy_type,
            carrier_hints_suffix=carrier_hint_block,
        )
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ENDORSEMENT_SCHEMA,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        contents = [prompt]
        if active_cache:
            config.cached_content = active_cache.name
        else:
            contents.insert(0, uploaded_file)
        return self._transport.call_gemini(
            model=EXTRACTION_MODEL,
            contents=contents,
            config=config,
            request_type="endorsement_summary",
        )

    def _normalize_coi_result(self, raw_data: dict, fallback_classification: dict) -> dict:
        """Delegate for tests / backward compatibility."""
        return normalize_coi_result(raw_data, fallback_classification)

    def _apply_auto_liability_rules(self, coverages, policy_type):
        """Delegate for tests / backward compatibility."""
        apply_auto_liability_rules(coverages, policy_type)


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
