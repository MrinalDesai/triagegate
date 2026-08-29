"""LLM client abstractions for optional Granite tie-break voting."""

from __future__ import annotations

import json
import os
from typing import Callable, Optional, Protocol, Sequence, Tuple


class LLMClient(Protocol):
    """Minimal interface for an LLM-based domain classifier."""

    def classify(
        self,
        title: str,
        description: str,
        domains: Sequence[str],
    ) -> Optional[Tuple[str, float]]:
        """Return ``(domain, confidence)`` or *None* on any failure."""
        ...


class GraniteClient:
    """Calls IBM watsonx.ai Granite via the ibm-watsonx-ai SDK.

    Credentials are read from environment variables (or a ``.env`` file):
    - ``WATSONX_API_KEY``
    - ``WATSONX_PROJECT_ID``
    - ``WATSONX_URL``
    """

    _MODEL_ID = "ibm/granite-4-h-small"

    def __init__(self) -> None:
        try:
            from dotenv import load_dotenv  # type: ignore

            load_dotenv()
        except ImportError:
            pass

        self._api_key = os.environ.get("WATSONX_API_KEY", "")
        self._project_id = os.environ.get("WATSONX_PROJECT_ID", "")
        self._url = os.environ.get("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")

    def classify(
        self,
        title: str,
        description: str,
        domains: Sequence[str],
    ) -> Optional[Tuple[str, float]]:
        """Ask Granite to pick one domain and return ``(domain, confidence)``."""
        try:
            from ibm_watsonx_ai import APIClient, Credentials  # type: ignore
            from ibm_watsonx_ai.foundation_models import ModelInference  # type: ignore

            credentials = Credentials(
                url=self._url,
                api_key=self._api_key,
            )
            client = APIClient(credentials)

            model = ModelInference(
                model_id=self._MODEL_ID,
                api_client=client,
                project_id=self._project_id,
            )

            domain_list = ", ".join(f'"{d}"' for d in domains)
            prompt = (
                f"You are a software bug triage assistant. "
                f"Given the bug report below, pick exactly one domain from the list "
                f"[{domain_list}] that best describes the bug.\n\n"
                f"Bug title: {title}\n"
                f"Bug description: {description}\n\n"
                f'Reply with only valid JSON in the form {{"domain": "<chosen_domain>", "confidence": <float 0-1>}}. '
                f"No other text."
            )

            response = model.chat(
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response["choices"][0]["message"]["content"]
            return _parse_llm_json(raw, domains)
        except Exception:  # noqa: BLE001
            return None


def _parse_llm_json(
    raw: str,
    domains: Sequence[str],
) -> Optional[Tuple[str, float]]:
    """Extract the first JSON object from *raw* and validate it defensively."""
    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        obj = json.loads(raw[start:end])
        domain = str(obj.get("domain", "")).strip().lower()
        confidence = float(obj.get("confidence", 0.0))
        if domain not in domains:
            return None
        return (domain, confidence)
    except Exception:  # noqa: BLE001
        return None


class StubLLMClient:
    """Test double: delegates to a callable handler instead of a real LLM.

    Parameters
    ----------
    handler:
        A callable that receives ``(title, description, domains)`` and returns
        ``Optional[Tuple[str, float]]`` — the same signature as ``classify``.
    """

    def __init__(
        self,
        handler: Callable[[str, str, Sequence[str]], Optional[Tuple[str, float]]],
    ) -> None:
        self._handler = handler

    def classify(
        self,
        title: str,
        description: str,
        domains: Sequence[str],
    ) -> Optional[Tuple[str, float]]:
        return self._handler(title, description, domains)
