from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple

from .xml_utils import sanitize_jmx_xml


def parse_jmx(data: bytes) -> Tuple[ET.ElementTree, int]:
    """Parse a JMX file after aggressive recorder-safe XML sanitization."""
    cleaned, fixes = sanitize_jmx_xml(data)

    parse_attempts: List[bytes] = [cleaned]

    # Last-resort cleanup for malformed ampersands sometimes created when JMX
    # content is copied from logs or chat instead of uploaded as the raw file.
    text = cleaned.decode("UTF-8", errors="replace")
    text = re.sub(
        r"&(?!amp;|lt;|gt;|quot;|apos;|#[0-9]+;|#[xX][0-9A-Fa-f]+;)",
        "&amp;",
        text,
    )
    parse_attempts.append(text.encode("UTF-8"))

    last_error: Optional[ET.ParseError] = None
    for candidate in parse_attempts:
        try:
            return ET.ElementTree(ET.fromstring(candidate)), fixes
        except ET.ParseError as exc:
            last_error = exc

    # Optional recovery if lxml is installed. The app itself does not require
    # lxml, but this gives one more recovery path for badly copied recorder XML.
    try:
        from lxml import etree as LET  # type: ignore

        parser = LET.XMLParser(recover=True, resolve_entities=False, huge_tree=True)
        recovered = LET.fromstring(parse_attempts[-1], parser=parser)
        recovered_bytes = LET.tostring(recovered, encoding="UTF-8", xml_declaration=True)
        return ET.ElementTree(ET.fromstring(recovered_bytes)), fixes
    except Exception:
        if last_error is not None:
            raise last_error
        raise
