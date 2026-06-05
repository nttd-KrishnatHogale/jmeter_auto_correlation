from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Tuple

from .config import NUMERIC_CHAR_REF_BYTES_RE, NUMERIC_CHAR_REF_RE, XML_DECL_RE


def get_encoding(data: bytes) -> str:
    match = XML_DECL_RE.search(data[:200])
    return match.group(1).decode("ascii", "ignore") if match else "UTF-8"


def is_valid_xml_char(codepoint: int) -> bool:
    return (
        codepoint in (0x09, 0x0A, 0x0D)
        or 0x20 <= codepoint <= 0xD7FF
        or 0xE000 <= codepoint <= 0xFFFD
        or 0x10000 <= codepoint <= 0x10FFFF
    )


def strip_invalid_numeric_refs_bytes(data: bytes) -> Tuple[bytes, int]:
    """Remove XML-invalid numeric character references at byte level."""
    replacements = 0

    def fix_ref(match: re.Match[bytes]) -> bytes:
        nonlocal replacements
        raw = match.group(1) or match.group(2)
        base = 16 if match.group(1) else 10
        try:
            codepoint = int(raw.decode("ascii"), base)
        except ValueError:
            replacements += 1
            return b""
        if is_valid_xml_char(codepoint):
            return match.group(0)
        replacements += 1
        return b""

    return NUMERIC_CHAR_REF_BYTES_RE.sub(fix_ref, data), replacements


def sanitize_jmx_xml(data: bytes) -> Tuple[bytes, int]:
    """Remove XML-invalid characters/character references from recorder output."""
    data, replacements = strip_invalid_numeric_refs_bytes(data)

    encoding = get_encoding(data)
    text = data.decode(encoding, errors="replace")

    def fix_ref(match: re.Match[str]) -> str:
        nonlocal replacements
        raw = match.group(1) or match.group(2)
        base = 16 if match.group(1) else 10
        try:
            codepoint = int(raw, base)
        except ValueError:
            replacements += 1
            return ""
        if is_valid_xml_char(codepoint):
            return match.group(0)
        replacements += 1
        return ""

    text = NUMERIC_CHAR_REF_RE.sub(fix_ref, text)

    cleaned_chars = []
    for char in text:
        if is_valid_xml_char(ord(char)):
            cleaned_chars.append(char)
        else:
            replacements += 1

    cleaned = "".join(cleaned_chars)
    return cleaned.encode("UTF-8"), replacements


def describe_parse_position(data: bytes, error: ET.ParseError) -> str:
    """Return a short diagnostic around the parser error position."""
    line_no, col_no = getattr(error, "position", (None, None)) or (None, None)
    if not line_no:
        return ""

    text = data.decode(get_encoding(data), errors="replace")
    lines = text.splitlines()
    if not (1 <= line_no <= len(lines)):
        return ""

    line = lines[line_no - 1]
    start = max(0, col_no - 80)
    end = min(len(line), col_no + 160)
    snippet = line[start:end]
    return f"Line {line_no}, column {col_no} around error:\n{snippet!r}"


def local_tag(tag: str) -> str:
    """Return XML tag name without namespace."""
    return tag.rsplit("}", 1)[-1]


def indent(elem: ET.Element, level: int = 0) -> None:
    """Pretty-print XML using ElementTree-compatible indentation."""
    indentation = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indentation + "  "
        for child in elem:
            indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indentation
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = indentation
