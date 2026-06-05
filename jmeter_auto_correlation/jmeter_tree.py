from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Iterable, List, Optional, Tuple

from .models import Sampler
from .xml_utils import local_tag


def is_http_sampler(elem: ET.Element) -> bool:
    tag = local_tag(elem.tag)
    testclass = elem.attrib.get("testclass", "")
    return tag in {"HTTPSamplerProxy", "HTTPSampler"} or "HTTPSampler" in testclass


def is_header_manager(elem: ET.Element) -> bool:
    tag = local_tag(elem.tag)
    testclass = elem.attrib.get("testclass", "")
    return tag == "HeaderManager" or "HeaderManager" in testclass


def is_regex_extractor(elem: ET.Element) -> bool:
    tag = local_tag(elem.tag)
    testclass = elem.attrib.get("testclass", "")
    return tag == "RegexExtractor" or "RegexExtractor" in testclass


def element_name(elem: ET.Element, default: str) -> str:
    return elem.attrib.get("testname") or elem.attrib.get("name") or default


def children_list(parent: ET.Element) -> List[ET.Element]:
    return list(parent)


def collect_samplers(root: ET.Element) -> List[Sampler]:
    samplers: List[Sampler] = []

    def walk(parent: ET.Element) -> None:
        kids = children_list(parent)
        for i, child in enumerate(kids):
            if is_http_sampler(child):
                next_hash_tree = (
                    kids[i + 1]
                    if i + 1 < len(kids) and local_tag(kids[i + 1].tag) == "hashTree"
                    else None
                )
                idx = len(samplers)
                sampler = Sampler(
                    index=idx,
                    name=element_name(child, f"HTTP Request {idx + 1}"),
                    elem=child,
                    hash_tree=next_hash_tree,
                    text_nodes=list(iter_string_value_nodes(child)),
                    header_nodes=(
                        list(iter_header_value_nodes(next_hash_tree))
                        if next_hash_tree is not None
                        else []
                    ),
                )
                samplers.append(sampler)
            walk(child)

    walk(root)
    return samplers


def iter_string_value_nodes(elem: ET.Element) -> Iterable[ET.Element]:
    """Yield JMeter property nodes that can contain request values."""
    interesting_names = (
        "HTTPSampler.path",
        "Argument.value",
        "Argument.name",
        "HTTPArgument.value",
        "HTTPArgument.name",
        "HTTPSampler.postBodyRaw",
        "HTTPSampler.domain",
        "HTTPSampler.port",
        "HTTPSampler.protocol",
    )
    for node in elem.iter():
        if local_tag(node.tag) in {"stringProp", "boolProp", "intProp", "longProp"}:
            name = node.attrib.get("name", "")
            if (
                name.startswith(interesting_names)
                or "Argument.value" in name
                or "HTTPArgument.value" in name
            ):
                yield node
        elif (
            local_tag(node.tag) == "elementProp"
            and node.attrib.get("elementType") in {"HTTPArgument", "Argument"}
        ):
            # Child stringProps are yielded by recursion; this branch documents intent.
            continue


def iter_header_value_nodes(hash_tree: Optional[ET.Element]) -> Iterable[ET.Element]:
    if hash_tree is None:
        return
    for header_manager in hash_tree.iter():
        if is_header_manager(header_manager):
            for node in header_manager.iter():
                if (
                    local_tag(node.tag) == "stringProp"
                    and node.attrib.get("name") == "Header.value"
                ):
                    yield node


def iter_argument_pairs(sampler: Sampler) -> Iterable[Tuple[str, str, ET.Element]]:
    for argument in sampler.elem.iter():
        if (
            local_tag(argument.tag) != "elementProp"
            or argument.attrib.get("elementType") not in {"HTTPArgument", "Argument"}
        ):
            continue

        name_node = None
        value_node = None
        for child in argument:
            if (
                local_tag(child.tag) == "stringProp"
                and child.attrib.get("name") in {"Argument.name", "HTTPArgument.name"}
            ):
                name_node = child
            if (
                local_tag(child.tag) == "stringProp"
                and child.attrib.get("name") in {"Argument.value", "HTTPArgument.value"}
            ):
                value_node = child

        if value_node is not None:
            yield (
                name_node.text or "" if name_node is not None else "",
                value_node.text or "",
                value_node,
            )


def node_value(node: ET.Element) -> str:
    return node.text or ""
