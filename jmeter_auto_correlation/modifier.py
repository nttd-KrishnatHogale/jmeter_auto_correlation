from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from typing import Dict, List, Tuple

from .jmeter_tree import collect_samplers, is_regex_extractor, iter_argument_pairs
from .models import Candidate, Sampler
from .xml_utils import indent, local_tag


def make_regex_extractor(candidate: Candidate) -> ET.Element:
    elem = ET.Element(
        "RegexExtractor",
        {
            "guiclass": "RegexExtractorGui",
            "testclass": "RegexExtractor",
            "testname": f"Extract_{candidate.variable_name}",
            "enabled": "true",
        },
    )
    props = [
        ("RegexExtractor.useHeaders", "false"),
        ("RegexExtractor.refname", candidate.variable_name),
        ("RegexExtractor.regex", candidate.extraction_pattern),
        ("RegexExtractor.template", "$1$"),
        ("RegexExtractor.default", "NOT_FOUND"),
        ("RegexExtractor.match_number", "1"),
    ]
    for name, value in props:
        child = ET.SubElement(elem, "stringProp", {"name": name})
        child.text = value
    return elem


def extractor_exists(sampler: Sampler, variable_name: str) -> bool:
    if sampler.hash_tree is None:
        return False

    for elem in sampler.hash_tree.iter():
        if is_regex_extractor(elem):
            for child in elem.iter():
                if (
                    local_tag(child.tag) == "stringProp"
                    and child.attrib.get("name") == "RegexExtractor.refname"
                    and (child.text or "") == variable_name
                ):
                    return True
    return False


def replace_value_in_sampler(
    sampler: Sampler,
    sample_value: str,
    variable_name: str,
    parameter_name: str,
) -> int:
    replacement = "${" + variable_name + "}"
    count = 0

    for name, value, value_node in iter_argument_pairs(sampler):
        if name.lower() == parameter_name.lower():
            if value_node.text != replacement:
                value_node.text = replacement
                count += 1
        elif sample_value and len(sample_value) > 8 and sample_value in value:
            value_node.text = value.replace(sample_value, replacement)
            count += 1

    for node in sampler.text_nodes + sampler.header_nodes:
        text = node.text or ""
        if sample_value and len(sample_value) > 8 and sample_value in text:
            node.text = text.replace(sample_value, replacement)
            count += 1

    return count


def apply_candidates(
    tree: ET.ElementTree,
    candidates: List[Candidate],
    selected_ids: List[str],
    source_overrides: Dict[str, int],
) -> Tuple[bytes, int, int]:
    root = tree.getroot()
    samplers = collect_samplers(root)
    by_id = {candidate.id: candidate for candidate in candidates}
    added_extractors = 0
    replacements = 0

    for candidate_id in selected_ids:
        candidate = by_id[candidate_id]
        source_index = int(source_overrides.get(candidate_id, candidate.source_sampler_index))

        if 0 <= source_index < len(samplers):
            source = samplers[source_index]
            if source.hash_tree is not None and not extractor_exists(source, candidate.variable_name):
                source.hash_tree.append(make_regex_extractor(candidate))
                source.hash_tree.append(ET.Element("hashTree"))
                added_extractors += 1

        for index in candidate.target_sampler_indices:
            if 0 <= index < len(samplers):
                replacements += replace_value_in_sampler(
                    samplers[index],
                    candidate.sample_value,
                    candidate.variable_name,
                    candidate.parameter_name,
                )

    indent(root)
    output = io.BytesIO()
    tree.write(output, encoding="UTF-8", xml_declaration=True)
    return output.getvalue(), added_extractors, replacements
