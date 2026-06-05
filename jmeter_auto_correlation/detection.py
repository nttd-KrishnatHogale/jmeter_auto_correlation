from __future__ import annotations

import re
import uuid
from typing import Dict, List, Optional, Tuple

from .config import DYNAMIC_NAME_PATTERNS, JWT_RE, LONG_TOKEN_RE
from .jmeter_tree import iter_argument_pairs, node_value
from .models import Candidate, Sampler


def looks_dynamic_name(name: str) -> Optional[str]:
    for pattern, correlation_type in DYNAMIC_NAME_PATTERNS:
        if re.search(pattern, name or ""):
            return correlation_type
    return None


def looks_dynamic_value(value: str) -> bool:
    if not value or "${" in value or len(value) < 8:
        return False
    if JWT_RE.match(value):
        return True
    if len(value) >= 12 and LONG_TOKEN_RE.match(value):
        has_alpha = bool(re.search(r"[A-Za-z]", value))
        has_digit = bool(re.search(r"\d", value))
        has_special = bool(re.search(r"[_.:/+=-]", value))
        return len(value) >= 32 or (has_alpha and (has_digit or has_special))
    return False


def classify(name: str, value: str) -> str:
    by_name = looks_dynamic_name(name)
    if by_name:
        return by_name
    if JWT_RE.match(value):
        return "AUTH_TOKEN"
    if re.fullmatch(r"\d{10,13}", value or ""):
        return "TIMESTAMP"
    return "CUSTOM"


def confidence(name: str, value: str, correlation_type: str, usage_count: int) -> float:
    score = 0.35
    if looks_dynamic_name(name):
        score += 0.25
    if correlation_type in {"SESSION_ID", "CSRF_TOKEN", "VIEWSTATE", "AUTH_TOKEN"}:
        score += 0.15
    if len(value) > 32:
        score += 0.1
    if re.search(r"[A-Z]", value) and re.search(r"[a-z]", value) and re.search(r"\d", value):
        score += 0.1
    if usage_count > 1:
        score += 0.05
    return min(round(score, 2), 1.0)


def make_variable_name(name: str, correlation_type: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_]", "_", name or correlation_type).upper().strip("_") or correlation_type
    return base if base.startswith(correlation_type) else f"{correlation_type}_{base}"


def regex_escape(value: str) -> str:
    return re.escape(value)


def extraction_pattern(name: str, correlation_type: str) -> str:
    escaped = regex_escape(name)
    if correlation_type == "SESSION_ID":
        return rf"(?i)\b{escaped}=([A-Za-z0-9_%-]+)"
    if correlation_type == "AUTH_TOKEN":
        return rf"\\?\"?{escaped}\\?\"?\s*:\s*\\?\"([^\"\\]+)"
    if correlation_type in {"CSRF_TOKEN", "HIDDEN_FIELD"}:
        return rf"<input(?=[^>]*\bname=[\"']{escaped}[\"'])[^>]*\bvalue=[\"']([^\"']+)[\"']|\"?{escaped}\"?\s*[:=]\s*\"?([^\"\s,}}<;]+)"
    return rf"\"?{escaped}\"?\s*(?:value\s*=|content\s*=|[:=])\s*\"?([^\"\s,}}<;]+)\"?"


def inferred_name_from_value(value: str) -> str:
    if JWT_RE.match(value):
        return "token"
    return "dynamic_value"


def detect_candidates(
    samplers: List[Sampler],
    min_length: int = 8,
    require_reuse: bool = True,
) -> List[Candidate]:
    occurrences: Dict[Tuple[str, str], List[int]] = {}
    reasons: Dict[Tuple[str, str], str] = {}

    for sampler in samplers:
        for name, value, _node in iter_argument_pairs(sampler):
            if len(value or "") < min_length or "${" in value:
                continue

            correlation_type = looks_dynamic_name(name)
            if correlation_type or looks_dynamic_value(value):
                key = (name or inferred_name_from_value(value), value)
                occurrences.setdefault(key, []).append(sampler.index)
                reasons[key] = (
                    "parameter name matched known dynamic token"
                    if correlation_type
                    else "value looks generated/encoded"
                )

        for node in sampler.text_nodes + sampler.header_nodes:
            value = node_value(node)
            if len(value) >= min_length and "${" not in value and looks_dynamic_value(value):
                name = node.attrib.get("name", "value")
                key = (name, value)
                occurrences.setdefault(key, []).append(sampler.index)
                reasons[key] = "request field/header value looks generated/encoded"

    candidates: List[Candidate] = []
    seen_vars: set[str] = set()

    for (name, value), indexes in occurrences.items():
        unique_indexes = sorted(set(indexes))
        if require_reuse and len(unique_indexes) < 1:
            continue

        # JMX-only mode cannot know the true response source; infer previous sampler.
        first_index = unique_indexes[0]
        source_index = max(0, first_index - 1)
        correlation_type = classify(name, value)
        variable_name = make_variable_name(name, correlation_type)

        original_variable_name = variable_name
        suffix = 2
        while variable_name in seen_vars:
            variable_name = f"{original_variable_name}_{suffix}"
            suffix += 1
        seen_vars.add(variable_name)

        candidate_confidence = confidence(name, value, correlation_type, len(unique_indexes))
        candidates.append(
            Candidate(
                id=str(uuid.uuid4()),
                parameter_name=name,
                sample_value=value,
                correlation_type=correlation_type,
                extractor_type="REGEX",
                confidence=candidate_confidence,
                variable_name=variable_name,
                first_sampler_index=first_index,
                source_sampler_index=source_index,
                target_sampler_indices=unique_indexes,
                extraction_pattern=extraction_pattern(name, correlation_type),
                reason=reasons.get((name, value), "dynamic-looking value"),
            )
        )

    return sorted(candidates, key=lambda candidate: (-candidate.confidence, candidate.first_sampler_index, candidate.parameter_name))
