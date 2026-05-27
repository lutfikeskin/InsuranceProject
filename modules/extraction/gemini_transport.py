"""Gemini file upload, context cache lifecycle, and budgeted generate_content calls."""

import os
import tempfile
import time
from datetime import datetime, timezone

from google.genai import types

from core.constants import DEFAULT_DAILY_BUDGET
from core.logger import logger
from core.telemetry import TelemetryService, log_event, new_correlation_id
from core.services import UsageService

from .extraction_local_cache import ExtractionCache

ROUTING_MODEL = "gemini-3.1-flash-lite"
EXTRACTION_MODEL = "gemini-3.1-flash-lite"


class GeminiTransport:
    def __init__(self, client, usage_service: UsageService):
        self.client = client
        self.usage_service = usage_service
        self.telemetry = TelemetryService(usage_service.session)
        self._last_call_retries = 0

    def upload_to_gemini(self, file_bytes: bytes):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        try:
            return self.client.files.upload(file=tmp_path)
        finally:
            os.remove(tmp_path)

    def create_cache(self, uploaded_file, ttl="300s"):
        """Creates a temporary context cache for this document."""
        try:
            cache = self.client.caches.create(
                model=EXTRACTION_MODEL,
                config=types.CreateCachedContentConfig(
                    display_name="insurance_extraction_ctx",
                    system_instruction="You are an expert insurance underwriter and data extraction specialist.",
                    contents=[uploaded_file],
                    ttl=ttl,
                ),
            )
            logger.info(f"CACHE CREATED: {cache.name} (TTL: {ttl})")
            return cache
        except Exception as e:
            logger.warning(
                f"Failed to create cache: {e}. Falling back to standard upload."
            )
            return None

    def _is_retryable_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        markers = [
            "429",
            "rate limit",
            "resource exhausted",
            "timeout",
            "temporarily unavailable",
            "internal error",
            "503",
            "500",
        ]
        return any(m in msg for m in markers)

    def get_reusable_cache(self, file_hash: str, cache_system: ExtractionCache):
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
                expire_time = datetime.fromisoformat(
                    expire_time_raw.replace("Z", "+00:00")
                )
                if datetime.now(timezone.utc) >= expire_time:
                    return None
            except Exception:
                pass

        try:
            cache = self.client.caches.get(name=cache_name)
            logger.info(f"CACHE REUSED: {cache_name}")
            return cache
        except Exception as e:
            logger.info(f"Cache reuse miss: {e}")
            return None

    def call_gemini(
        self,
        model: str,
        contents: list,
        config: types.GenerateContentConfig,
        request_type: str = "extraction",
        correlation_id: str | None = None,
    ):
        """Centralized wrapper to enforce daily budget and log usage."""
        correlation_id = correlation_id or new_correlation_id("llm")
        if self.usage_service.is_over_budget(daily_limit=DEFAULT_DAILY_BUDGET):
            message = (
                f"STOPS: API Daily Quota Exceeded (${DEFAULT_DAILY_BUDGET}). "
                "Processing halted to prevent billing."
            )
            self.usage_service.log_usage(
                model_name=model,
                input_tokens=0,
                output_tokens=0,
                request_type=request_type,
                cached_input_tokens=0,
                status="budget_blocked",
                correlation_id=correlation_id,
                error_message=message,
                latency_ms=0,
            )
            log_event(
                "llm_budget_blocked",
                level="warning",
                correlation_id=correlation_id,
                status="budget_blocked",
                metadata={"model": model, "request_type": request_type, "budget": DEFAULT_DAILY_BUDGET},
                message=message,
            )
            raise Exception(message)

        config.temperature = 0.0

        max_retries = 2
        attempt = 0
        response = None
        started_at = time.perf_counter()
        last_error: Exception | None = None
        while attempt <= max_retries:
            try:
                response = self.client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
                break
            except Exception as e:
                last_error = e
                if attempt >= max_retries or not self._is_retryable_error(e):
                    break
                sleep_s = 1.5 ** attempt
                retry_metadata = {
                    "model": model,
                    "request_type": request_type,
                    "attempt": attempt + 1,
                    "error": str(e),
                }
                self.telemetry.record_event(
                    "llm_retry",
                    category="llm",
                    status="retrying",
                    correlation_id=correlation_id,
                    count_value=1,
                    metadata=retry_metadata,
                )
                log_event(
                    "llm_retry",
                    level="warning",
                    correlation_id=correlation_id,
                    status="retrying",
                    metadata=retry_metadata,
                )
                time.sleep(sleep_s)
                attempt += 1
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)

        if response is None:
            error_message = str(last_error) if last_error else "LLM call failed"
            self.usage_service.log_usage(
                model_name=model,
                input_tokens=0,
                output_tokens=0,
                request_type=request_type,
                cached_input_tokens=0,
                status="failure",
                correlation_id=correlation_id,
                error_message=error_message,
                latency_ms=elapsed_ms,
            )
            log_event(
                "llm_failed",
                level="error",
                correlation_id=correlation_id,
                status="failure",
                duration_ms=elapsed_ms,
                metadata={
                    "model": model,
                    "request_type": request_type,
                    "retries": attempt,
                    "error": error_message,
                },
            )
            self._last_call_retries = attempt
            if last_error is not None:
                raise last_error
            raise Exception(error_message)

        if response.usage_metadata:
            cached_tokens = (
                response.usage_metadata.cached_content_token_count or 0
            )
            log_event(
                "llm_usage",
                correlation_id=correlation_id,
                status="success",
                duration_ms=elapsed_ms,
                metadata={
                    "model": model,
                    "request_type": request_type,
                    "input_tokens": response.usage_metadata.prompt_token_count or 0,
                    "cached_tokens": cached_tokens,
                    "output_tokens": response.usage_metadata.candidates_token_count or 0,
                    "retries": attempt,
                },
            )
            self.usage_service.log_usage(
                model_name=model,
                input_tokens=response.usage_metadata.prompt_token_count or 0,
                output_tokens=response.usage_metadata.candidates_token_count or 0,
                request_type=request_type,
                cached_input_tokens=cached_tokens,
                status="success",
                correlation_id=correlation_id,
                latency_ms=elapsed_ms,
            )
        self._last_call_retries = attempt

        return response
