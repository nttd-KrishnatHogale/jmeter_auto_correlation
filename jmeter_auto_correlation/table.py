from __future__ import annotations

from typing import List

import pandas as pd

from .models import Candidate, Sampler


def candidates_to_df(candidates: List[Candidate], samplers: List[Sampler]) -> pd.DataFrame:
    rows = []
    for candidate in candidates:
        rows.append(
            {
                "selected": candidate.confidence >= 0.7,
                "id": candidate.id,
                "parameter": candidate.parameter_name,
                "type": candidate.correlation_type,
                "extractor": candidate.extractor_type,
                "confidence": candidate.confidence_level,
                "score": candidate.confidence,
                "source_sampler": (
                    samplers[candidate.source_sampler_index].name
                    if samplers
                    else ""
                ),
                "used_in": len(candidate.target_sampler_indices),
                "target_samplers": ", ".join(
                    samplers[index].name
                    for index in candidate.target_sampler_indices
                    if index < len(samplers)
                ),
                "variable": candidate.variable_name,
                "sample_value": candidate.sample_value[:80]
                + ("..." if len(candidate.sample_value) > 80 else ""),
                "reason": candidate.reason,
            }
        )
    return pd.DataFrame(rows)
