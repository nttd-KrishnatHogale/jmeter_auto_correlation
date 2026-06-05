from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Sampler:
    index: int
    name: str
    elem: ET.Element
    hash_tree: Optional[ET.Element]
    text_nodes: List[ET.Element]
    header_nodes: List[ET.Element]


@dataclass
class Candidate:
    id: str
    parameter_name: str
    sample_value: str
    correlation_type: str
    extractor_type: str
    confidence: float
    variable_name: str
    first_sampler_index: int
    source_sampler_index: int
    target_sampler_indices: List[int]
    extraction_pattern: str
    reason: str

    @property
    def confidence_level(self) -> str:
        if self.confidence >= 0.8:
            return "High"
        if self.confidence >= 0.5:
            return "Medium"
        return "Low"
