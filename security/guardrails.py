"""Local PII redaction and Groq-backed user-input guardrails."""

import logging
import os
import re
from typing import Literal

from groq import Groq
from pydantic import BaseModel


logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PROMPT_GUARD_MODEL = os.getenv(
    "PROMPT_GUARD_MODEL", "meta-llama/llama-prompt-guard-2-22m"
)
LLAMA_GUARD_MODEL = os.getenv("LLAMA_GUARD_MODEL", "llama-guard-3-8b")
PROMPT_GUARD_BLOCK_THRESHOLD = 0.5

SAFETY_POLICY = """# User Content Safety Policy

Classify the supplied user content. Return JSON only with these keys:
`violation` (0 or 1), `category` (string or null), and `rationale` (string).

Set `violation` to 1 when the content requests, instructs, facilitates, or
meaningfully enables violent wrongdoing, self-harm, sexual exploitation,
criminal activity, evasion of safety controls, or disclosure of personal or
confidential data. Set `violation` to 0 for benign informational requests.
Do not treat a user voluntarily providing their own non-sensitive work city,
work location, job role, employer, or career preference as personal-data
disclosure. Those self-profile updates are benign. Sensitive identifiers are
redacted locally before this policy is evaluated.
Use a concise, human-readable category when violation is 1."""

EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
CARD_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){12,15}\d(?!\d)")
PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:\+\d{1,3}[ .-]?)?(?:\(?\d{3}\)?[ .-]?)?\d{3}[ .-]?\d{4}(?!\d)"
)
OPENAI_KEY_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]+")
GITHUB_KEY_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])ghp_[A-Za-z0-9]+")
TAVILY_KEY_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])tvly-[A-Za-z0-9_-]+")
BEARER_TOKEN_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
SELF_PROFILE_UPDATE_PATTERN = re.compile(
    r"\b(?:my|i\s+am|i'm)\b.{0,80}\b(?:"
    r"work(?:\s+location)?|office|city|job(?:\s+role)?|role|employer|career"
    r")\b",
    re.IGNORECASE,
)
PERSONAL_DATA_DISCLOSURE_CATEGORY = re.compile(
    r"\b(?:personal|private|confidential)\s+(?:data|information)\s+disclosure\b",
    re.IGNORECASE,
)
LOCAL_REDACTION_MARKERS = frozenset(
    {
        "[EMAIL_REDACTED]",
        "[PHONE_REDACTED]",
        "[CARD_REDACTED]",
        "[SECRET_REDACTED]",
    }
)


class GuardrailResult(BaseModel):
    """The outcome of the user-input security boundary."""

    is_safe: bool
    sanitized_prompt: str
    flag_reason: str | None = None


class SafeguardAssessment(BaseModel):
    """Structured policy decision returned by GPT-OSS Safeguard."""

    violation: Literal[0, 1]
    category: str | None = None
    rationale: str | None = None


def anonymize_pii(prompt: str) -> str:
    """Redact supported PII and credentials before any cloud request.

    Args:
        prompt: Raw user input.

    Returns:
        The prompt with supported sensitive values replaced by stable markers.
    """
    sanitized = CARD_PATTERN.sub("[CARD_REDACTED]", prompt)
    sanitized = EMAIL_PATTERN.sub("[EMAIL_REDACTED]", sanitized)
    sanitized = PHONE_PATTERN.sub("[PHONE_REDACTED]", sanitized)
    sanitized = OPENAI_KEY_PATTERN.sub("[SECRET_REDACTED]", sanitized)
    sanitized = GITHUB_KEY_PATTERN.sub("[SECRET_REDACTED]", sanitized)
    sanitized = TAVILY_KEY_PATTERN.sub("[SECRET_REDACTED]", sanitized)
    return BEARER_TOKEN_PATTERN.sub("[SECRET_REDACTED]", sanitized)


def _response_text(response: object) -> str:
    """Extract a normalized text completion from the Groq SDK response."""
    choices = getattr(response, "choices", [])
    if not choices:
        return ""
    return (
        getattr(getattr(choices[0], "message", None), "content", None) or ""
    ).strip()


def _screen_with_groq(
    client: Groq,
    model: str,
    messages: list[dict[str, str]],
) -> str:
    """Run one deterministic Groq guard model check."""
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.0,
    )
    return _response_text(response)


def _moderation_category(response_text: str) -> str:
    """Extract Llama Guard's category code from its unsafe response."""
    lines = [line.strip() for line in response_text.splitlines() if line.strip()]
    return lines[1] if len(lines) > 1 else "UNKNOWN"


def _prompt_guard_blocks(response_text: str) -> bool:
    """Interpret Prompt Guard's numeric risk score or legacy textual output."""
    classification = response_text.lower()
    if (
        "injection" in classification
        or "jailbreak" in classification
        or classification.startswith("unsafe")
    ):
        return True
    try:
        return float(response_text) >= PROMPT_GUARD_BLOCK_THRESHOLD
    except ValueError:
        return False


def _safeguard_category(response_text: str) -> str | None:
    """Return the category from GPT-OSS JSON or a legacy Llama Guard response."""
    try:
        assessment = SafeguardAssessment.model_validate_json(response_text)
    except ValueError:
        if response_text.lower().startswith("unsafe"):
            return _moderation_category(response_text)
        return None
    return assessment.category if assessment.violation else None


def _is_benign_self_profile_update(prompt: str) -> bool:
    """Return whether a sanitized prompt is a non-sensitive self-profile update."""
    return SELF_PROFILE_UPDATE_PATTERN.search(prompt) is not None and not any(
        marker in prompt for marker in LOCAL_REDACTION_MARKERS
    )


def _is_self_profile_false_positive(category: str, prompt: str) -> bool:
    """Identify a personal-data label incorrectly applied to a benign self-update."""
    return PERSONAL_DATA_DISCLOSURE_CATEGORY.search(
        category
    ) is not None and _is_benign_self_profile_update(prompt)


def scan_user_input(prompt: str) -> GuardrailResult:
    """Redact local PII, then screen the sanitized prompt for unsafe content.

    If Groq is unavailable, local redaction is still applied and the caller receives
    a safe pass-through result with an explicit availability warning.

    Args:
        prompt: Raw user input to inspect.

    Returns:
        A guardrail outcome containing only the sanitized prompt.
    """
    sanitized_prompt = anonymize_pii(prompt)

    if not GROQ_API_KEY:
        logger.warning(
            "GROQ_API_KEY is not configured; skipping cloud guardrail screening"
        )
        return GuardrailResult(is_safe=True, sanitized_prompt=sanitized_prompt)

    try:
        client = Groq(api_key=GROQ_API_KEY)
        prompt_guard_output = _screen_with_groq(
            client,
            PROMPT_GUARD_MODEL,
            [{"role": "user", "content": sanitized_prompt}],
        )
        if _prompt_guard_blocks(prompt_guard_output):
            return GuardrailResult(
                is_safe=False,
                sanitized_prompt=sanitized_prompt,
                flag_reason="Prompt Injection / Jailbreak Attempt Detected",
            )

        safeguard_output = _screen_with_groq(
            client,
            LLAMA_GUARD_MODEL,
            [
                {"role": "system", "content": SAFETY_POLICY},
                {"role": "user", "content": sanitized_prompt},
            ],
        )
        category = _safeguard_category(safeguard_output)
        if category is not None:
            if _is_self_profile_false_positive(category, sanitized_prompt):
                logger.info(
                    "Allowing benign self-profile update misclassified as personal-data disclosure"
                )
                return GuardrailResult(is_safe=True, sanitized_prompt=sanitized_prompt)
            return GuardrailResult(
                is_safe=False,
                sanitized_prompt=sanitized_prompt,
                flag_reason=f"Content Moderation Flagged: {category}",
            )
        return GuardrailResult(is_safe=True, sanitized_prompt=sanitized_prompt)
    except Exception:
        logger.warning(
            "Groq guardrail screening failed; allowing sanitized input", exc_info=True
        )
        return GuardrailResult(
            is_safe=True,
            sanitized_prompt=sanitized_prompt,
            flag_reason="Guardrail screening unavailable",
        )
