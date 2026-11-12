# -*- coding: utf-8 -*-
"""
llm_client.py
=============
Shared Gemini LLM client module for LawExamData.

Provides unified SDK resolution (modern ``google.genai`` primary, falling back
to legacy ``google.generativeai`` strictly on ``ImportError``), structured error
classification, bounded per-model exponential backoff with jitter, diagnostic
empty-response handling, and deterministic JSON decoding without greedy regexes.
"""

from __future__ import annotations

import json
import random
import re
import socket
import time
from typing import Any, Callable, Dict, Optional, Tuple

import config


class LlmCallError(Exception):
    """Base error for all LLM invocation or response-parsing failures."""


class MissingApiKeyError(LlmCallError):
    """Raised when no Gemini API key is configured from any source."""


class AuthError(LlmCallError):
    """Raised on fast-fail authentication/authorization errors (401/403/invalid key)."""


class TransientRateLimitError(LlmCallError):
    """Raised when all candidate models fail due to rate limits, 5xx, or timeouts."""


_AUTH_MESSAGE_MARKERS = (
    "api_key_invalid",
    "api key not valid",
    "invalid api key",
    "api_key_service_blocked",
    "unauthenticated",
    "unauthorized",
    "permission_denied",
    "permission denied",
)

_TRANSIENT_MESSAGE_MARKERS = (
    "resource_exhausted",
    "resource exhausted",
    "rate limit",
    "rate_limit",
    "too many requests",
    "quota",
    "service unavailable",
    "unavailable",
    "overloaded",
    "deadline_exceeded",
    "deadline exceeded",
    "timed out",
    "timeout",
    "temporarily",
)


def _get_status_code(exc: BaseException) -> Optional[int]:
    for attr in ("code", "status_code", "http_status"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    return None


def _is_auth_error(exc: BaseException) -> bool:
    code = _get_status_code(exc)
    if code in (401, 403):
        return True
    msg = str(exc).lower()
    if any(marker in msg for marker in _AUTH_MESSAGE_MARKERS):
        return True
    return bool(re.search(r"\b(401|403)\b", msg))


def _is_transient_error(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    code = _get_status_code(exc)
    if code in (408, 429, 500, 502, 503, 504):
        return True
    msg = str(exc).lower()
    if any(marker in msg for marker in _TRANSIENT_MESSAGE_MARKERS):
        return True
    return bool(re.search(r"\b(408|429|500|502|503|504)\b", msg))


def _load_sdk() -> Tuple[str, Any, Any]:
    """Load modern ``google.genai`` first; fall back to ``google.generativeai`` only on ImportError."""
    try:
        from google import genai as modern_genai
        from google.genai import types as modern_types
        return ("modern", modern_genai, modern_types)
    except ImportError:
        try:
            import google.generativeai as legacy_genai
            return ("legacy", legacy_genai, None)
        except ImportError as exc:
            raise LlmCallError(
                "Neither 'google-genai' nor 'google-generativeai' is installed."
            ) from exc


def _extract_response_text(resp: Any, model_name: str) -> str:
    """Validate non-empty ``resp.text`` and raise diagnostic error on blocked/empty outputs."""
    text_err: Optional[Exception] = None
    text: Optional[str] = None
    try:
        text = getattr(resp, "text", None)
    except Exception as exc:
        text_err = exc

    if isinstance(text, str) and text.strip():
        return text

    finish_reasons = []
    safety_details = []
    candidates = getattr(resp, "candidates", None)
    if candidates:
        for cand in candidates:
            fr = getattr(cand, "finish_reason", None)
            if fr is not None:
                finish_reasons.append(str(fr))
            sr = getattr(cand, "safety_ratings", None)
            if sr:
                safety_details.append(str(sr))

    prompt_feedback = getattr(resp, "prompt_feedback", None)
    block_reason = getattr(prompt_feedback, "block_reason", None) if prompt_feedback is not None else None
    if prompt_feedback is not None and not safety_details:
        pf_safety = getattr(prompt_feedback, "safety_ratings", None)
        if pf_safety:
            safety_details.append(str(pf_safety))

    diag_parts = [f"model={model_name}"]
    if finish_reasons:
        diag_parts.append(f"finish_reason={','.join(finish_reasons)}")
    if block_reason is not None:
        diag_parts.append(f"block_reason={block_reason}")
    if safety_details:
        diag_parts.append(f"safety={'; '.join(safety_details)}")
    if text_err is not None:
        diag_parts.append(f"accessor_error={text_err}")

    raise LlmCallError(f"Gemini returned empty response ({', '.join(diag_parts)}).")


def _invoke_modern(
    types_mod: Any,
    client: Any,
    model_name: str,
    contents: Any,
    *,
    temperature: float,
    max_output_tokens: Optional[int],
    response_mime_type: Optional[str],
    system_instruction: Optional[str],
) -> Any:
    cfg_kwargs: Dict[str, Any] = {"temperature": temperature}
    if max_output_tokens is not None:
        cfg_kwargs["max_output_tokens"] = max_output_tokens
    if response_mime_type is not None:
        cfg_kwargs["response_mime_type"] = response_mime_type
    if system_instruction is not None:
        cfg_kwargs["system_instruction"] = system_instruction
    gen_config = types_mod.GenerateContentConfig(**cfg_kwargs)
    return client.models.generate_content(
        model=model_name,
        contents=contents,
        config=gen_config,
    )


def _invoke_legacy(
    legacy_mod: Any,
    model_name: str,
    contents: Any,
    *,
    temperature: float,
    max_output_tokens: Optional[int],
    response_mime_type: Optional[str],
    system_instruction: Optional[str],
) -> Any:
    gen_cfg_kwargs: Dict[str, Any] = {"temperature": temperature}
    if max_output_tokens is not None:
        gen_cfg_kwargs["max_output_tokens"] = max_output_tokens
    if response_mime_type is not None:
        gen_cfg_kwargs["response_mime_type"] = response_mime_type

    model_kwargs: Dict[str, Any] = {}
    if system_instruction is not None:
        model_kwargs["system_instruction"] = system_instruction

    model_obj = legacy_mod.GenerativeModel(model_name=model_name, **model_kwargs)
    return model_obj.generate_content(contents, generation_config=gen_cfg_kwargs)


def _backoff_sleep(attempt: int) -> None:
    delay = min(8.0, 0.75 * (2 ** attempt)) + random.uniform(0.0, 0.35)
    time.sleep(delay)


def generate_content(
    contents: Any,
    *,
    primary_model: Optional[str] = None,
    temperature: float = 0.2,
    max_output_tokens: Optional[int] = None,
    response_mime_type: Optional[str] = None,
    system_instruction: Optional[str] = None,
    api_key: Optional[str] = None,
    max_retries_per_model: int = 2,
) -> str:
    """
    Generate text content via Gemini with resilient model fallback and retry backoff.

    Raises:
        MissingApiKeyError: When no API key is available from explicit arg, session, secrets, or env.
        AuthError: Immediately on 401/403 or invalid API key errors.
        TransientRateLimitError: When all models fail due to 429/5xx/timeouts.
        LlmCallError: On non-empty response validation errors or exhausted model fallbacks.
    """
    resolved_key = config.get_gemini_api_key(api_key)
    if not resolved_key:
        raise MissingApiKeyError(
            "Gemini API key is missing. Provide api_key, set session key, or configure GEMINI_API_KEY."
        )

    sdk_kind, sdk_mod, types_mod = _load_sdk()
    if sdk_kind == "modern":
        client = sdk_mod.Client(api_key=resolved_key)
    else:
        sdk_mod.configure(api_key=resolved_key)
        client = None

    models_to_try = config.get_gemini_models_to_try(primary_model)
    retries = max(0, int(max_retries_per_model))

    last_err: Optional[BaseException] = None
    saw_transient = False
    saw_non_transient = False

    for model_name in models_to_try:
        for attempt in range(retries + 1):
            try:
                if sdk_kind == "modern":
                    resp = _invoke_modern(
                        types_mod,
                        client,
                        model_name,
                        contents,
                        temperature=temperature,
                        max_output_tokens=max_output_tokens,
                        response_mime_type=response_mime_type,
                        system_instruction=system_instruction,
                    )
                else:
                    resp = _invoke_legacy(
                        sdk_mod,
                        model_name,
                        contents,
                        temperature=temperature,
                        max_output_tokens=max_output_tokens,
                        response_mime_type=response_mime_type,
                        system_instruction=system_instruction,
                    )
                return _extract_response_text(resp, model_name)
            except LlmCallError as exc:
                last_err = exc
                saw_non_transient = True
                break
            except Exception as exc:
                if _is_auth_error(exc):
                    raise AuthError(f"Gemini API authentication error: {exc}") from exc
                last_err = exc
                if _is_transient_error(exc):
                    saw_transient = True
                    if attempt < retries:
                        _backoff_sleep(attempt)
                        continue
                    break
                saw_non_transient = True
                break

    if saw_transient and not saw_non_transient:
        raise TransientRateLimitError(
            f"All Gemini candidate models failed due to rate limit or transient errors: {last_err}"
        ) from last_err
    if isinstance(last_err, LlmCallError):
        raise last_err
    raise LlmCallError(f"All Gemini candidate models failed: {last_err}") from last_err


def _strip_outer_fences(text: str) -> str:
    cleaned = text.strip()
    obj_idx = cleaned.find("{")
    arr_idx = cleaned.find("[")
    json_positions = [idx for idx in (obj_idx, arr_idx) if idx != -1]
    first_json_pos = min(json_positions) if json_positions else -1

    fence_match = re.search(r"```(?:json)?\s*(?:\r?\n|$)", cleaned, flags=re.IGNORECASE)
    if fence_match and (first_json_pos == -1 or fence_match.start() < first_json_pos):
        cleaned = cleaned[fence_match.end():]
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)

    return cleaned.strip()


def _decode_first_json(text: str) -> Any:
    cleaned = _strip_outer_fences(text)
    obj_idx = cleaned.find("{")
    arr_idx = cleaned.find("[")
    candidates = [idx for idx in (obj_idx, arr_idx) if idx != -1]
    if not candidates:
        raise ValueError("No JSON object '{' or array '[' found in response.")
    start_idx = min(candidates)
    decoder = json.JSONDecoder()
    parsed, _ = decoder.raw_decode(cleaned, start_idx)
    return parsed


def parse_json_response(
    raw_text: Optional[str],
    *,
    repair_fn: Optional[Callable[[str], Optional[str]]] = None,
) -> Any:
    """
    Parse JSON cleanly from an LLM response using ``JSONDecoder().raw_decode``.

    Strips outer markdown `````json`` / ````` fences without touching inner string
    values, finds the first ``{`` or ``[``, and optionally invokes ``repair_fn``
    once on parse failure before raising ``LlmCallError``.
    """
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise LlmCallError("Empty or non-string LLM response; expected JSON.")

    try:
        return _decode_first_json(raw_text)
    except (ValueError, json.JSONDecodeError) as first_err:
        if repair_fn is not None:
            try:
                repaired = repair_fn(raw_text)
            except Exception as repair_exc:
                raise LlmCallError(
                    f"JSON parse failed ({first_err}) and repair_fn raised: {repair_exc}"
                ) from repair_exc

            if isinstance(repaired, str) and repaired.strip():
                try:
                    return _decode_first_json(repaired)
                except (ValueError, json.JSONDecodeError) as second_err:
                    raise LlmCallError(
                        f"Failed to parse JSON response after repair: {second_err}"
                    ) from second_err
            raise LlmCallError(
                f"Failed to parse JSON response ({first_err}); repair_fn returned empty text."
            ) from first_err

        raise LlmCallError(f"Failed to parse JSON response: {first_err}") from first_err


def generate_json(
    contents: Any,
    *,
    primary_model: Optional[str] = None,
    temperature: float = 0.2,
    max_output_tokens: Optional[int] = None,
    system_instruction: Optional[str] = None,
    api_key: Optional[str] = None,
    max_retries_per_model: int = 2,
    repair_fn: Optional[Callable[[str], Optional[str]]] = None,
) -> Any:
    """Call ``generate_content`` with JSON MIME type and parse the JSON response."""
    raw_text = generate_content(
        contents,
        primary_model=primary_model,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        response_mime_type="application/json",
        system_instruction=system_instruction,
        api_key=api_key,
        max_retries_per_model=max_retries_per_model,
    )
    return parse_json_response(raw_text, repair_fn=repair_fn)
