This Python file is a **Streamlit web app** that helps with **JMeter auto-correlation**.

Its goal is:

1. Upload a JMeter `.jmx` file.
2. Parse the JMX XML safely, even if it contains invalid recorder-generated characters.
3. Find hardcoded dynamic values such as session IDs, CSRF tokens, JWTs, timestamps, API keys, etc.
4. Show those values as correlation candidates.
5. Let the user choose which candidates to apply.
6. Add JMeter **Regex Extractors** to the likely source sampler.
7. Replace hardcoded values in later requests with JMeter variables like `${CSRF_TOKEN_X}`.
8. Download the modified correlated `.jmx` file.

---

## 1. Future import

```python
from __future__ import annotations
```

This makes type hints behave more flexibly. For example, classes can reference types that are defined later without causing issues. It also avoids evaluating annotations immediately.

---

## 2. Imports

```python
import html
import io
import re
import sys
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
```

These are standard Python libraries.

`io` is used for writing XML into an in-memory byte buffer.

`re` is used heavily for regular expressions.

`sys` is used to check command-line arguments like `--self-test`.

`uuid` is used to create unique IDs for detected correlation candidates.

`xml.etree.ElementTree as ET` is Python’s built-in XML parser/writer.

`dataclass` is used to define simple structured classes.

`html` and `asdict` are imported but not actually used in this code.

---

```python
try:
    from lxml import etree as LET
except Exception:
    LET = None
```

This tries to import `lxml`, an optional XML library. `lxml` can recover from malformed XML better than Python’s default XML parser.

In this file, the top-level `LET` variable is not really used later because `lxml` is imported again inside `parse_jmx()`. So this import is mostly redundant.

---

```python
from typing import Dict, Iterable, List, Optional, Tuple
```

These are type-hint helpers.

For example:

```python
List[Candidate]
Dict[str, int]
Optional[ET.Element]
Tuple[bytes, int]
```

---

```python
import pandas as pd
```

Pandas is used to build a table of detected candidates for Streamlit’s editable data grid.

---

## 3. App version

```python
APP_VERSION = "v5-byte-cleaner-2026-06-03"
```

This stores a version label for the app. It is shown in the Streamlit UI and in the self-test output.

---

## 4. Dynamic parameter name patterns

```python
DYNAMIC_NAME_PATTERNS: List[Tuple[str, str]] = [
    (r"(?i)^(j?sessionid|session_id|sid|phpsessid|aspsessionid)$", "SESSION_ID"),
    ...
]
```

This list maps regular-expression patterns to token categories.

For example:

```python
(r"(?i)^(j?sessionid|session_id|sid|phpsessid|aspsessionid)$", "SESSION_ID")
```

means:

If a parameter name looks like:

```text
JSESSIONID
session_id
sid
PHPSESSID
ASPSESSIONID
```

then classify it as:

```text
SESSION_ID
```

The `(?i)` part makes the regex case-insensitive.

Other categories include:

```text
CSRF_TOKEN
VIEWSTATE
AUTH_TOKEN
NONCE
TIMESTAMP
CORRELATION_ID
CUSTOM
```

These are used to guess whether a request parameter/header/body value is dynamic and should be correlated.

---

## 5. Token-detection regular expressions

```python
JWT_RE = re.compile(r"^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
```

This detects JWT-like values.

JWTs often begin with:

```text
eyJ
```

and have three base64url parts separated by dots:

```text
header.payload.signature
```

Example:

```text
eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signature
```

---

```python
LONG_TOKEN_RE = re.compile(r"^[A-Za-z0-9_./+=:-]{12,512}$")
```

This detects long token-looking strings made of letters, digits, and token-like symbols.

It accepts characters such as:

```text
_
.
/
+
=
:
-
```

and requires the length to be between 12 and 512 characters.

---

```python
XML_DECL_RE = re.compile(br"^\s*<\?xml[^>]*encoding=['\"]([^'\"]+)['\"]", re.I)
```

This checks the XML declaration at the start of the file to find the declared encoding.

Example:

```xml
<?xml version="1.0" encoding="UTF-8"?>
```

It extracts:

```text
UTF-8
```

The `b` prefix means this regex works on bytes, not normal strings.

---

```python
NUMERIC_CHAR_REF_RE = re.compile(r"&#(?:(?:[xX]([0-9A-Fa-f]+))|(\d+));?")
NUMERIC_CHAR_REF_BYTES_RE = re.compile(br"&#(?:(?:[xX]([0-9A-Fa-f]+))|(\d+));?")
```

These detect XML numeric character references like:

```xml
&#31;
&#x1f;
&#x8;
&#0;
```

The first regex works on strings.

The second regex works on bytes.

This is important because the app sanitizes invalid XML characters before parsing.

---

## 6. `Sampler` dataclass

```python
@dataclass
class Sampler:
    index: int
    name: str
    elem: ET.Element
    hash_tree: Optional[ET.Element]
    text_nodes: List[ET.Element]
    header_nodes: List[ET.Element]
```

A `Sampler` represents one JMeter HTTP request sampler found inside the JMX file.

Fields:

```python
index
```

The sampler’s position in the list of HTTP samplers.

```python
name
```

The display name of the sampler, usually from JMeter’s `testname` attribute.

```python
elem
```

The actual XML element for the HTTP sampler.

```python
hash_tree
```

The JMeter `<hashTree>` immediately following this sampler. In JMeter JMX files, child elements such as extractors usually live inside this associated hashTree.

```python
text_nodes
```

String-like XML nodes inside the sampler that may contain request values, such as paths, parameters, bodies, protocol, host, etc.

```python
header_nodes
```

Header value nodes found in a Header Manager associated with this sampler.

---

## 7. `Candidate` dataclass

```python
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
```

A `Candidate` represents one possible dynamic value that the app thinks should be correlated.

Example candidate:

```text
parameter_name: csrf_token
sample_value: abc123XYZ...
correlation_type: CSRF_TOKEN
variable_name: CSRF_TOKEN_CSRF_TOKEN
source_sampler_index: previous request
target_sampler_indices: requests where this hardcoded value appears
```

Important fields:

```python
id
```

Unique ID for the candidate.

```python
parameter_name
```

The request parameter/header/property name where the value was found.

```python
sample_value
```

The hardcoded value found in the JMX.

```python
correlation_type
```

Type guessed by the app, such as `SESSION_ID`, `CSRF_TOKEN`, `AUTH_TOKEN`, etc.

```python
extractor_type
```

Currently always `"REGEX"`.

```python
confidence
```

Numeric confidence score from `0.0` to `1.0`.

```python
variable_name
```

The JMeter variable name that will replace the hardcoded value.

Example:

```text
${CSRF_TOKEN_AUTHENTICITY_TOKEN}
```

```python
first_sampler_index
```

The first sampler where the value appears.

```python
source_sampler_index
```

The sampler where the extractor should be added. The app guesses this as the previous HTTP request.

```python
target_sampler_indices
```

The samplers where the hardcoded value will be replaced.

```python
extraction_pattern
```

Regex pattern used by the JMeter Regex Extractor.

```python
reason
```

Human-readable reason explaining why this value was detected.

---

### `confidence_level` property

```python
@property
def confidence_level(self) -> str:
    if self.confidence >= 0.8:
        return "High"
    if self.confidence >= 0.5:
        return "Medium"
    return "Low"
```

This converts the numeric confidence score into a readable label.

Examples:

```text
0.85 -> High
0.65 -> Medium
0.35 -> Low
```

---

## 8. XML character validation

```python
def is_valid_xml_char(codepoint: int) -> bool:
    return (
        codepoint in (0x09, 0x0A, 0x0D)
        or 0x20 <= codepoint <= 0xD7FF
        or 0xE000 <= codepoint <= 0xFFFD
        or 0x10000 <= codepoint <= 0x10FFFF
    )
```

This checks whether a Unicode character is valid in XML 1.0.

Allowed characters include:

```text
tab
newline
carriage return
normal printable Unicode ranges
```

Invalid XML characters include many control characters such as:

```text
&#x0;
&#x1;
&#x8;
&#x1f;
```

JMeter recordings can sometimes contain these when binary request bodies are stored in XML. XML parsers reject those files, so the app removes them before parsing.

---

## 9. Removing invalid numeric XML references from bytes

```python
def strip_invalid_numeric_refs_bytes(data: bytes) -> Tuple[bytes, int]:
```

This function removes invalid XML numeric character references before the file is decoded into text.

Example invalid references:

```xml
&#x1f;
&#x8;
&#0;
```

The function returns:

```python
(cleaned_bytes, number_of_replacements)
```

---

Inside it:

```python
replacements = 0
```

Tracks how many invalid references were removed.

---

```python
def fix_ref(match: re.Match[bytes]) -> bytes:
```

This nested function is called for every numeric character reference found by the regex.

---

```python
raw = match.group(1) or match.group(2)
base = 16 if match.group(1) else 10
```

The regex supports both hex and decimal references.

Examples:

```xml
&#x1f;  -> hex -> base 16
&#31;   -> decimal -> base 10
```

---

```python
cp = int(raw.decode("ascii"), base)
```

Converts the numeric reference into an integer codepoint.

---

```python
if is_valid_xml_char(cp):
    return match.group(0)
```

If the character is valid XML, keep it unchanged.

---

```python
replacements += 1
return b""
```

If invalid, remove it by replacing it with empty bytes.

---

```python
return NUMERIC_CHAR_REF_BYTES_RE.sub(fix_ref, data), replacements
```

Runs the substitution over the whole byte content.

---

## 10. Full JMX/XML sanitizer

```python
def sanitize_jmx_xml(data: bytes) -> Tuple[bytes, int]:
```

This function aggressively cleans a JMX file so XML parsing is less likely to fail.

It returns:

```python
(cleaned_xml_bytes, number_of_fixes)
```

---

First pass:

```python
data, replacements = strip_invalid_numeric_refs_bytes(data)
```

It removes invalid XML numeric references before decoding.

This is necessary because XML parsers fail even if invalid characters are escaped as numeric references.

---

Then:

```python
encoding = get_encoding(data)
text = data.decode(encoding, errors="replace")
```

It detects the XML encoding and decodes bytes into text.

If decoding fails for some characters, invalid bytes are replaced with the Unicode replacement character instead of crashing.

---

Second pass:

```python
def fix_ref(match: re.Match[str]) -> str:
```

This repeats the numeric-reference cleanup after decoding. It catches cases that the byte-level pass missed.

---

Then:

```python
text = NUMERIC_CHAR_REF_RE.sub(fix_ref, text)
```

Applies the text-level cleanup.

---

Then:

```python
cleaned_chars = []
for ch in text:
    if is_valid_xml_char(ord(ch)):
        cleaned_chars.append(ch)
    else:
        replacements += 1
```

This removes actual literal invalid XML characters, not just numeric references.

---

Finally:

```python
cleaned = "".join(cleaned_chars)
return cleaned.encode("UTF-8"), replacements
```

It encodes the cleaned XML as UTF-8 and returns it.

---

## 11. Parsing the JMX

```python
def parse_jmx(data: bytes) -> Tuple[ET.ElementTree, int]:
```

This parses the uploaded JMX file into an XML tree.

It returns:

```python
(parsed_tree, number_of_xml_fixes)
```

---

```python
cleaned, fixes = sanitize_jmx_xml(data)
```

First it sanitizes the XML.

---

```python
parse_attempts: List[bytes] = [cleaned]
```

It starts with one parse attempt: the cleaned XML.

---

```python
text = cleaned.decode("UTF-8", errors="replace")
text = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#[0-9]+;|#[xX][0-9A-Fa-f]+;)", "&amp;", text)
parse_attempts.append(text.encode("UTF-8"))
```

This creates a second parse attempt where malformed ampersands are escaped.

For example, raw XML like this is invalid:

```xml
/path?a=1&b=2
```

because `&b` looks like an entity.

It should be:

```xml
/path?a=1&amp;b=2
```

This regex replaces unsafe `&` with `&amp;`, while leaving valid XML entities alone.

---

```python
last_error: Optional[ET.ParseError] = None
for candidate in parse_attempts:
    try:
        return ET.ElementTree(ET.fromstring(candidate)), fixes
    except ET.ParseError as exc:
        last_error = exc
```

It tries each cleaned version with Python’s built-in XML parser.

If parsing succeeds, it returns the XML tree.

If parsing fails, it remembers the last parse error.

---

Fallback:

```python
try:
    from lxml import etree as LET
    parser = LET.XMLParser(recover=True, resolve_entities=False, huge_tree=True)
    recovered = LET.fromstring(parse_attempts[-1], parser=parser)
    recovered_bytes = LET.tostring(recovered, encoding="UTF-8", xml_declaration=True)
    return ET.ElementTree(ET.fromstring(recovered_bytes)), fixes
```

If normal parsing fails, it tries `lxml` recovery mode.

Important options:

```python
recover=True
```

Try to recover malformed XML.

```python
resolve_entities=False
```

Do not resolve external/internal entities. This is safer.

```python
huge_tree=True
```

Allows larger XML trees.

Then it converts the recovered lxml tree back into standard `ElementTree`.

---

If everything fails:

```python
except Exception:
    if last_error is not None:
        raise last_error
    raise
```

It raises the original parse error.

---

## 12. Parse-error diagnostics

```python
def describe_parse_position(data: bytes, error: ET.ParseError) -> str:
```

This creates a readable error snippet around the XML parse failure.

---

```python
line_no, col_no = getattr(error, "position", (None, None)) or (None, None)
```

Gets the line and column where parsing failed.

---

```python
text = data.decode(get_encoding(data), errors="replace")
lines = text.splitlines()
```

Decodes the XML and splits it into lines.

---

```python
line = lines[line_no - 1]
start = max(0, col_no - 80)
end = min(len(line), col_no + 160)
snippet = line[start:end]
```

Extracts text around the error position.

---

```python
return f"Line {line_no}, column {col_no} around error:\n{snippet!r}"
```

Returns a diagnostic string that Streamlit can display.

---

## 13. Encoding detection

```python
def get_encoding(data: bytes) -> str:
    m = XML_DECL_RE.search(data[:200])
    return m.group(1).decode("ascii", "ignore") if m else "UTF-8"
```

This checks the first 200 bytes of the file for an XML encoding declaration.

Example:

```xml
<?xml version="1.0" encoding="ISO-8859-1"?>
```

If found, it returns that encoding.

If not found, it assumes:

```text
UTF-8
```

---

## 14. Namespace-safe tag handling

```python
def local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
```

XML tags may include namespaces.

Example:

```text
{some-namespace}HTTPSamplerProxy
```

This function strips the namespace and returns:

```text
HTTPSamplerProxy
```

That makes tag comparisons easier.

---

## 15. Element type checkers

### HTTP sampler checker

```python
def is_http_sampler(elem: ET.Element) -> bool:
    tag = local_tag(elem.tag)
    testclass = elem.attrib.get("testclass", "")
    return tag in {"HTTPSamplerProxy", "HTTPSampler"} or "HTTPSampler" in testclass
```

Returns `True` if the XML element looks like a JMeter HTTP request sampler.

It checks both:

```python
tag
```

and:

```python
testclass
```

because different JMeter versions/plugins may store the type slightly differently.

---

### Header Manager checker

```python
def is_header_manager(elem: ET.Element) -> bool:
    tag = local_tag(elem.tag)
    testclass = elem.attrib.get("testclass", "")
    return tag == "HeaderManager" or "HeaderManager" in testclass
```

Returns `True` if the element is a JMeter Header Manager.

---

### Regex Extractor checker

```python
def is_regex_extractor(elem: ET.Element) -> bool:
    tag = local_tag(elem.tag)
    testclass = elem.attrib.get("testclass", "")
    return tag == "RegexExtractor" or "RegexExtractor" in testclass
```

Returns `True` if the element is a JMeter Regex Extractor.

---

## 16. Getting element names

```python
def element_name(elem: ET.Element, default: str) -> str:
    return elem.attrib.get("testname") or elem.attrib.get("name") or default
```

This gets a readable name for a JMeter element.

Priority:

1. `testname`
2. `name`
3. fallback default

---

## 17. Getting children

```python
def children_list(parent: ET.Element) -> List[ET.Element]:
    return list(parent)
```

This returns the direct child elements of an XML element as a list.

It is a tiny helper function.

---

## 18. Collecting HTTP samplers

```python
def collect_samplers(root: ET.Element) -> List[Sampler]:
```

This walks through the entire JMX XML tree and collects all HTTP samplers.

---

```python
samplers: List[Sampler] = []
```

This list will store all discovered `Sampler` objects.

---

```python
def walk(parent: ET.Element) -> None:
```

Nested recursive function that walks through the XML tree.

---

```python
kids = children_list(parent)
for i, child in enumerate(kids):
```

Gets all children of the current parent and loops through them.

---

```python
if is_http_sampler(child):
```

If the child is an HTTP sampler, process it.

---

```python
next_hash_tree = kids[i + 1] if i + 1 < len(kids) and local_tag(kids[i + 1].tag) == "hashTree" else None
```

In a JMeter JMX file, an element is usually followed by a matching `<hashTree>`.

Example:

```xml
<HTTPSamplerProxy ...>
    ...
</HTTPSamplerProxy>
<hashTree>
    child elements like Regex Extractors
</hashTree>
```

So this line grabs the sampler’s associated `hashTree`.

---

```python
idx = len(samplers)
```

The sampler index is based on how many samplers have already been found.

---

```python
sampler = Sampler(
    index=idx,
    name=element_name(child, f"HTTP Request {idx + 1}"),
    elem=child,
    hash_tree=next_hash_tree,
    text_nodes=list(iter_string_value_nodes(child)),
    header_nodes=list(iter_header_value_nodes(next_hash_tree)) if next_hash_tree is not None else [],
)
```

Creates a `Sampler` object.

It collects:

```python
text_nodes
```

from inside the HTTP sampler.

And:

```python
header_nodes
```

from the associated Header Manager, if one exists.

---

```python
samplers.append(sampler)
```

Adds the sampler to the list.

---

```python
walk(child)
```

Continues recursively walking into child elements.

---

```python
walk(root)
return samplers
```

Starts the recursive walk at the root and returns all samplers found.

---

## 19. Finding request value nodes

```python
def iter_string_value_nodes(elem: ET.Element) -> Iterable[ET.Element]:
```

This yields XML nodes inside a sampler that may contain useful request values.

Examples include:

```text
request path
argument names
argument values
raw body flag
domain
port
protocol
```

---

```python
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
```

These are JMeter property names the app considers worth scanning.

---

```python
for node in elem.iter():
```

Walks through the sampler and all its descendants.

---

```python
if local_tag(node.tag) in {"stringProp", "boolProp", "intProp", "longProp"}:
```

JMeter stores many properties in these XML tags.

Examples:

```xml
<stringProp name="Argument.value">abc123</stringProp>
<boolProp name="HTTPSampler.postBodyRaw">true</boolProp>
```

---

```python
name = node.attrib.get("name", "")
if name.startswith(interesting_names) or "Argument.value" in name or "HTTPArgument.value" in name:
    yield node
```

If the property name is interesting, yield that node.

---

```python
elif local_tag(node.tag) == "elementProp" and node.attrib.get("elementType") in {"HTTPArgument", "Argument"}:
    continue
```

This branch does nothing except make the code’s intent clearer. Child `stringProp` nodes will already be handled by the recursion.

---

## 20. Finding header value nodes

```python
def iter_header_value_nodes(hash_tree: Optional[ET.Element]) -> Iterable[ET.Element]:
```

This finds HTTP header values from a sampler’s associated `hashTree`.

---

```python
if hash_tree is None:
    return
```

If there is no associated hashTree, there are no header nodes to scan.

Because this function contains `yield` later, `return` simply ends the generator.

---

```python
for hm in hash_tree.iter():
    if is_header_manager(hm):
```

Searches for Header Manager elements.

---

```python
for node in hm.iter():
    if local_tag(node.tag) == "stringProp" and node.attrib.get("name") == "Header.value":
        yield node
```

Yields every header value.

Example:

```xml
<stringProp name="Header.value">Bearer abc123</stringProp>
```

---

## 21. Iterating request argument pairs

```python
def iter_argument_pairs(sampler: Sampler) -> Iterable[Tuple[str, str, ET.Element]]:
```

This yields request parameter pairs from an HTTP sampler.

Each yielded item is:

```python
(parameter_name, parameter_value, value_xml_node)
```

---

```python
for arg in sampler.elem.iter():
```

Walks through all XML elements under the sampler.

---

```python
if local_tag(arg.tag) != "elementProp" or arg.attrib.get("elementType") not in {"HTTPArgument", "Argument"}:
    continue
```

Only processes JMeter argument elements.

Example:

```xml
<elementProp name="csrf" elementType="HTTPArgument">
    <stringProp name="Argument.name">csrf</stringProp>
    <stringProp name="Argument.value">abc123</stringProp>
</elementProp>
```

---

```python
name_node = None
value_node = None
```

These will hold the XML nodes for the argument name and value.

---

```python
for child in arg:
```

Loops over direct children of the argument element.

---

```python
if local_tag(child.tag) == "stringProp" and child.attrib.get("name") in {"Argument.name", "HTTPArgument.name"}:
    name_node = child
```

Finds the parameter name node.

---

```python
if local_tag(child.tag) == "stringProp" and child.attrib.get("name") in {"Argument.value", "HTTPArgument.value"}:
    value_node = child
```

Finds the parameter value node.

---

```python
if value_node is not None:
    yield (name_node.text or "" if name_node is not None else "", value_node.text or "", value_node)
```

If a value exists, it yields:

```python
name text
value text
value node itself
```

The value node is included because later the code needs to modify it.

---

## 22. Getting node text

```python
def node_value(node: ET.Element) -> str:
    return node.text or ""
```

Returns the text inside an XML element.

If the text is `None`, returns an empty string instead.

---

## 23. Checking dynamic names

```python
def looks_dynamic_name(name: str) -> Optional[str]:
    for pattern, ctype in DYNAMIC_NAME_PATTERNS:
        if re.search(pattern, name or ""):
            return ctype
    return None
```

This checks whether a parameter/header/property name looks dynamic.

Example:

```python
looks_dynamic_name("csrf_token")
```

would return:

```text
CSRF_TOKEN
```

If nothing matches, it returns:

```python
None
```

---

## 24. Checking dynamic values

```python
def looks_dynamic_value(value: str) -> bool:
```

This checks whether a value looks generated, encoded, or token-like.

---

```python
if not value or "${" in value or len(value) < 8:
    return False
```

Rejects:

```text
empty values
values already using JMeter variables
short values
```

Example already correlated value:

```text
${SESSION_ID}
```

---

```python
if JWT_RE.match(value):
    return True
```

JWTs are treated as dynamic.

---

```python
if len(value) >= 12 and LONG_TOKEN_RE.match(value):
```

Long token-like strings are considered further.

---

```python
has_alpha = bool(re.search(r"[A-Za-z]", value))
has_digit = bool(re.search(r"\d", value))
has_special = bool(re.search(r"[_.:/+=-]", value))
```

Checks whether the value contains letters, digits, and/or special token characters.

---

```python
return len(value) >= 32 or (has_alpha and (has_digit or has_special))
```

The value is considered dynamic if:

1. It is at least 32 characters long, or
2. It has letters plus either digits or token-like special characters.

---

Otherwise:

```python
return False
```

---

## 25. Classifying candidate type

```python
def classify(name: str, value: str) -> str:
```

This assigns a type to a dynamic value.

---

```python
by_name = looks_dynamic_name(name)
if by_name:
    return by_name
```

If the name clearly indicates a type, use that.

Example:

```text
csrf_token -> CSRF_TOKEN
```

---

```python
if JWT_RE.match(value):
    return "AUTH_TOKEN"
```

JWT values are classified as authentication tokens.

---

```python
if re.fullmatch(r"\d{10,13}", value or ""):
    return "TIMESTAMP"
```

A 10 to 13 digit number is treated as a timestamp.

Examples:

```text
1717500000
1717500000000
```

---

```python
return "CUSTOM"
```

Fallback type.

---

## 26. Confidence scoring

```python
def confidence(name: str, value: str, ctype: str, usage_count: int) -> float:
```

This calculates how confident the app is that a value should be correlated.

---

```python
score = 0.35
```

Every candidate starts at `0.35`.

---

```python
if looks_dynamic_name(name):
    score += 0.25
```

If the name looks dynamic, confidence increases.

---

```python
if ctype in {"SESSION_ID", "CSRF_TOKEN", "VIEWSTATE", "AUTH_TOKEN"}:
    score += 0.15
```

Important known token types get another boost.

---

```python
if len(value) > 32:
    score += 0.1
```

Long values are more likely dynamic.

---

```python
if re.search(r"[A-Z]", value) and re.search(r"[a-z]", value) and re.search(r"\d", value):
    score += 0.1
```

Mixed uppercase, lowercase, and digits often indicate generated tokens.

---

```python
if usage_count > 1:
    score += 0.05
```

If the value appears in more than one sampler, confidence increases slightly.

---

```python
return min(round(score, 2), 1.0)
```

Rounds to two decimals and caps at `1.0`.

---

## 27. Making a variable name

```python
def make_variable_name(name: str, ctype: str) -> str:
```

This creates a valid JMeter variable name.

---

```python
base = re.sub(r"[^A-Za-z0-9_]", "_", name or ctype).upper().strip("_") or ctype
```

This:

1. Replaces invalid characters with underscores.
2. Converts to uppercase.
3. Removes leading/trailing underscores.
4. Falls back to the correlation type if empty.

Example:

```text
csrf-token -> CSRF_TOKEN
```

---

```python
return base if base.startswith(ctype) else f"{ctype}_{base}"
```

Ensures the variable name starts with the type.

Examples:

```python
make_variable_name("csrf_token", "CSRF_TOKEN")
```

might return:

```text
CSRF_TOKEN
```

but:

```python
make_variable_name("authenticity_token", "CSRF_TOKEN")
```

returns:

```text
CSRF_TOKEN_AUTHENTICITY_TOKEN
```

---

## 28. Regex escaping helper

```python
def regex_escape(s: str) -> str:
    return re.escape(s)
```

Escapes special regex characters.

Example:

```python
regex_escape("csrf.token")
```

returns a pattern that treats the dot as a literal dot, not as “any character”.

---

## 29. Building extraction regex patterns

```python
def extraction_pattern(name: str, ctype: str) -> str:
```

This creates the regex that JMeter’s Regex Extractor will use.

---

```python
escaped = regex_escape(name)
```

Escapes the parameter name before inserting it into a regex.

---

### Session ID pattern

```python
if ctype == "SESSION_ID":
    return rf"(?i)\b{escaped}=([A-Za-z0-9_%-]+)"
```

Looks for something like:

```text
JSESSIONID=ABC123
```

The capture group is:

```regex
([A-Za-z0-9_%-]+)
```

That is the value JMeter will extract.

---

### Auth token pattern

```python
if ctype == "AUTH_TOKEN":
    return rf"\\?\"?{escaped}\\?\"?\s*:\s*\\?\"([^\"\\]+)"
```

Looks for JSON-like token fields.

Example target text:

```json
"access_token": "abc123"
```

The pattern allows some escaping because responses may contain escaped JSON.

---

### CSRF / hidden-field pattern

```python
if ctype in {"CSRF_TOKEN", "HIDDEN_FIELD"}:
    return rf"<input(?=[^>]*\bname=[\"']{escaped}[\"'])[^>]*\bvalue=[\"']([^\"']+)[\"']|\"?{escaped}\"?\s*[:=]\s*\"?([^\"\s,}}<;]+)"
```

This tries two alternatives:

1. HTML input field:

```html
<input name="csrf_token" value="abc123">
```

2. JSON/key-value style:

```json
"csrf_token": "abc123"
```

Important caveat: this regex has two capture groups because of the `|` alternative. But the extractor template later uses only `$1$`. If the second alternative matches, the value may land in group 2 instead of group 1. That means some CSRF-style extractions may need manual adjustment.

---

### Generic pattern

```python
return rf"\"?{escaped}\"?\s*(?:value\s*=|content\s*=|[:=])\s*\"?([^\"\s,}}<;]+)\"?"
```

Fallback pattern for custom values.

It looks for patterns like:

```text
token=value
"token": "value"
token content="value"
```

---

## 30. Detecting correlation candidates

```python
def detect_candidates(samplers: List[Sampler], min_length: int = 8, require_reuse: bool = True) -> List[Candidate]:
```

This is the main detection function.

It scans all collected samplers and returns possible values that should be correlated.

---

```python
occurrences: Dict[Tuple[str, str], List[int]] = {}
names_for_value: Dict[str, str] = {}
reasons: Dict[Tuple[str, str], str] = {}
```

These dictionaries track found values.

`occurrences` maps:

```python
(parameter_name, value)
```

to a list of sampler indexes where that value appears.

`reasons` stores why a value was flagged.

`names_for_value` is assigned but not meaningfully used later.

---

### First scan: request parameters

```python
for sampler in samplers:
    for name, value, _node in iter_argument_pairs(sampler):
```

Loops through request parameters in every sampler.

---

```python
if len(value or "") < min_length or "${" in value:
    continue
```

Skips short values and values already using JMeter variables.

---

```python
ctype = looks_dynamic_name(name)
```

Checks whether the parameter name looks dynamic.

---

```python
if ctype or looks_dynamic_value(value):
```

A parameter becomes a candidate if either:

1. Its name looks dynamic, or
2. Its value looks dynamic.

---

```python
key = (name or inferred_name_from_value(value), value)
```

Uses the parameter name if available. If the name is missing, it infers a generic name.

---

```python
occurrences.setdefault(key, []).append(sampler.index)
```

Records that this value appears in this sampler.

---

```python
names_for_value[value] = name or names_for_value.get(value, "value")
```

Stores a name for the value, but this dictionary is not used later.

---

```python
reasons[key] = "parameter name matched known dynamic token" if ctype else "value looks generated/encoded"
```

Stores the reason for detection.

---

### Second scan: text nodes and headers

```python
for node in sampler.text_nodes + sampler.header_nodes:
    value = node_value(node)
```

Checks other sampler fields and header values.

---

```python
if len(value) >= min_length and "${" not in value and looks_dynamic_value(value):
```

If the value is long enough, not already variableized, and token-like, it is a candidate.

---

```python
name = node.attrib.get("name", "value")
key = (name, value)
occurrences.setdefault(key, []).append(sampler.index)
reasons[key] = "request field/header value looks generated/encoded"
```

Records it.

---

### Building `Candidate` objects

```python
candidates: List[Candidate] = []
seen_vars: set[str] = set()
```

`candidates` stores final candidate objects.

`seen_vars` prevents duplicate variable names.

---

```python
for (name, value), idxs in occurrences.items():
    unique_idxs = sorted(set(idxs))
```

For each found value, get the unique sampler indexes where it appears.

---

```python
if require_reuse and len(unique_idxs) < 1:
    continue
```

This condition currently has almost no effect, because every occurrence has at least one sampler index.

The UI label says:

```text
Only show values that appear in at least one request
```

but every detected value already appears in at least one request.

If the intended behavior was “only show values reused in multiple requests,” this should probably be:

```python
if require_reuse and len(unique_idxs) < 2:
    continue
```

---

```python
first_idx = unique_idxs[0]
source_idx = max(0, first_idx - 1)
```

The app cannot see actual server response bodies from the JMX, so it guesses that the value was produced by the previous sampler.

Example:

```text
value first used in sampler 5
extract from sampler 4
```

If the first sampler is index `0`, source also becomes `0`.

---

```python
ctype = classify(name, value)
var_name = make_variable_name(name, ctype)
```

Classifies the token and creates a JMeter variable name.

---

```python
original_var = var_name
suffix = 2
while var_name in seen_vars:
    var_name = f"{original_var}_{suffix}"
    suffix += 1
seen_vars.add(var_name)
```

Ensures variable names are unique.

Example:

```text
CSRF_TOKEN
CSRF_TOKEN_2
CSRF_TOKEN_3
```

---

```python
conf = confidence(name, value, ctype, len(unique_idxs))
```

Calculates confidence.

---

```python
candidates.append(
    Candidate(...)
)
```

Creates and stores the candidate.

---

```python
return sorted(candidates, key=lambda c: (-c.confidence, c.first_sampler_index, c.parameter_name))
```

Returns candidates sorted by:

1. Highest confidence first.
2. Earlier sampler first.
3. Parameter name alphabetically.

---

## 31. Inferring a name from a value

```python
def inferred_name_from_value(value: str) -> str:
    if JWT_RE.match(value):
        return "token"
    return "dynamic_value"
```

If a parameter has no name, this guesses a generic name.

JWTs become:

```text
token
```

Other values become:

```text
dynamic_value
```

---

## 32. Creating a JMeter Regex Extractor

```python
def make_regex_extractor(candidate: Candidate) -> ET.Element:
```

This builds the XML for a JMeter Regex Extractor.

---

```python
elem = ET.Element(
    "RegexExtractor",
    {
        "guiclass": "RegexExtractorGui",
        "testclass": "RegexExtractor",
        "testname": f"Extract_{candidate.variable_name}",
        "enabled": "true",
    },
)
```

Creates this kind of JMeter element:

```xml
<RegexExtractor
    guiclass="RegexExtractorGui"
    testclass="RegexExtractor"
    testname="Extract_VARIABLE"
    enabled="true">
```

---

```python
props = [
    ("RegexExtractor.useHeaders", "false"),
    ("RegexExtractor.refname", candidate.variable_name),
    ("RegexExtractor.regex", candidate.extraction_pattern),
    ("RegexExtractor.template", "$1$"),
    ("RegexExtractor.default", "NOT_FOUND"),
    ("RegexExtractor.match_number", "1"),
]
```

These are the Regex Extractor settings.

Meaning:

```python
RegexExtractor.useHeaders = false
```

Extract from response body, not response headers.

```python
RegexExtractor.refname = candidate.variable_name
```

Store extracted value in this JMeter variable.

```python
RegexExtractor.regex = candidate.extraction_pattern
```

Use this regex.

```python
RegexExtractor.template = "$1$"
```

Use capture group 1 as the extracted value.

```python
RegexExtractor.default = "NOT_FOUND"
```

If no match is found, set the variable to `NOT_FOUND`.

```python
RegexExtractor.match_number = "1"
```

Use the first regex match.

---

```python
for name, value in props:
    child = ET.SubElement(elem, "stringProp", {"name": name})
    child.text = value
```

Adds each property as a child XML element.

---

```python
return elem
```

Returns the completed Regex Extractor XML element.

---

## 33. Checking whether an extractor already exists

```python
def extractor_exists(sampler: Sampler, variable_name: str) -> bool:
```

This prevents adding duplicate extractors for the same variable.

---

```python
if sampler.hash_tree is None:
    return False
```

If there is no hashTree, there cannot be an extractor.

---

```python
for elem in sampler.hash_tree.iter():
    if is_regex_extractor(elem):
```

Searches inside the sampler’s hashTree for Regex Extractors.

---

```python
for child in elem.iter():
    if local_tag(child.tag) == "stringProp" and child.attrib.get("name") == "RegexExtractor.refname" and (child.text or "") == variable_name:
        return True
```

If a Regex Extractor already stores into the same variable name, return `True`.

---

```python
return False
```

Otherwise no existing extractor was found.

---

## 34. Replacing hardcoded values in samplers

```python
def replace_value_in_sampler(sampler: Sampler, sample_value: str, variable_name: str, parameter_name: str) -> int:
```

This replaces hardcoded values with JMeter variables.

Example:

```text
abc123
```

becomes:

```text
${CSRF_TOKEN}
```

It returns the number of replacements made.

---

```python
replacement = "${" + variable_name + "}"
count = 0
```

Builds the replacement string.

---

### Replace exact parameter by name

```python
for name, value, value_node in iter_argument_pairs(sampler):
    if name.lower() == parameter_name.lower():
        if value_node.text != replacement:
            value_node.text = replacement
            count += 1
```

If a request argument has the same parameter name, the entire value is replaced.

Example:

```xml
<stringProp name="Argument.name">csrf_token</stringProp>
<stringProp name="Argument.value">abc123</stringProp>
```

becomes:

```xml
<stringProp name="Argument.value">${CSRF_TOKEN}</stringProp>
```

---

### Replace sample value inside parameter value

```python
elif sample_value and len(sample_value) > 8 and sample_value in value:
    value_node.text = value.replace(sample_value, replacement)
    count += 1
```

If the sample value appears inside a larger string, replace only that part.

Example:

```text
Bearer abc123
```

becomes:

```text
Bearer ${AUTH_TOKEN}
```

---

### Replace inside other text/header nodes

```python
for node in sampler.text_nodes + sampler.header_nodes:
    txt = node.text or ""
    if sample_value and len(sample_value) > 8 and sample_value in txt:
        node.text = txt.replace(sample_value, replacement)
        count += 1
```

This also replaces values in paths, raw body-like fields, and headers.

---

```python
return count
```

Returns how many replacements were made.

---

## 35. XML pretty-print indentation

```python
def indent(elem: ET.Element, level: int = 0) -> None:
```

This manually formats XML with indentation.

It is similar to `ET.indent()`, but works on older Python versions.

---

```python
i = "\n" + level * "  "
```

Creates indentation text.

At level 0:

```text
"\n"
```

At level 1:

```text
"\n  "
```

At level 2:

```text
"\n    "
```

---

```python
if len(elem):
```

If the element has child elements, format them.

---

```python
if not elem.text or not elem.text.strip():
    elem.text = i + "  "
```

Sets whitespace before the first child.

---

```python
for child in elem:
    indent(child, level + 1)
```

Recursively indents children.

---

```python
if not child.tail or not child.tail.strip():
    child.tail = i
```

Sets whitespace after the last child.

Note: `child` is only defined if the element had children. That is safe here because this block is inside `if len(elem)`.

---

```python
if level and (not elem.tail or not elem.tail.strip()):
    elem.tail = i
```

Adds whitespace after this element if it is not the root.

---

## 36. Applying selected candidates

```python
def apply_candidates(
    tree: ET.ElementTree,
    candidates: List[Candidate],
    selected_ids: List[str],
    source_overrides: Dict[str, int]
) -> Tuple[bytes, int, int]:
```

This modifies the JMX tree.

It returns:

```python
(new_jmx_bytes, added_extractors_count, replacements_count)
```

---

```python
root = tree.getroot()
samplers = collect_samplers(root)
by_id = {c.id: c for c in candidates}
added_extractors = 0
replacements = 0
```

Gets the root XML element, recollects samplers, and builds a lookup from candidate ID to candidate object.

---

```python
for cid in selected_ids:
    c = by_id[cid]
```

Loops over only the candidates the user selected in the UI.

---

```python
source_idx = int(source_overrides.get(cid, c.source_sampler_index))
```

Uses the user-selected source sampler if provided. Otherwise uses the candidate’s inferred source sampler.

---

### Add Regex Extractor

```python
if 0 <= source_idx < len(samplers):
    source = samplers[source_idx]
    if source.hash_tree is not None and not extractor_exists(source, c.variable_name):
        source.hash_tree.append(make_regex_extractor(c))
        source.hash_tree.append(ET.Element("hashTree"))
        added_extractors += 1
```

If the source sampler is valid:

1. Get its associated `hashTree`.
2. Check that the extractor does not already exist.
3. Append a new Regex Extractor.
4. Append an empty `<hashTree>` after it, because JMeter elements are usually paired with hashTrees.
5. Increment the added extractor count.

The resulting structure is like:

```xml
<RegexExtractor ...>
    ...
</RegexExtractor>
<hashTree />
```

---

### Replace values in target samplers

```python
for idx in c.target_sampler_indices:
    if 0 <= idx < len(samplers):
        replacements += replace_value_in_sampler(
            samplers[idx],
            c.sample_value,
            c.variable_name,
            c.parameter_name
        )
```

For every sampler where the hardcoded value appeared, replace it with `${VARIABLE}`.

---

### Write output XML

```python
indent(root)
out = io.BytesIO()
tree.write(out, encoding="UTF-8", xml_declaration=True)
return out.getvalue(), added_extractors, replacements
```

Pretty-prints the XML, writes it into bytes, and returns the result.

---

## 37. Converting candidates to a Pandas DataFrame

```python
def candidates_to_df(candidates: List[Candidate], samplers: List[Sampler]) -> pd.DataFrame:
```

This creates the table shown in the Streamlit UI.

---

```python
rows = []
for c in candidates:
    rows.append({...})
```

Builds one row per candidate.

Columns include:

```python
"selected": c.confidence >= 0.7
```

Candidates with confidence at least `0.7` are selected by default.

---

```python
"id": c.id
```

Internal candidate ID.

---

```python
"parameter": c.parameter_name
"type": c.correlation_type
"extractor": c.extractor_type
"confidence": c.confidence_level
"score": c.confidence
```

Basic candidate metadata.

---

```python
"source_sampler": samplers[c.source_sampler_index].name if samplers else ""
```

Shows the sampler where the Regex Extractor will be added.

---

```python
"used_in": len(c.target_sampler_indices)
```

How many samplers use the hardcoded value.

---

```python
"target_samplers": ", ".join(...)
```

Names of samplers where replacements will be made.

---

```python
"variable": c.variable_name
```

Editable JMeter variable name.

---

```python
"sample_value": c.sample_value[:80] + ("..." if len(c.sample_value) > 80 else "")
```

Shows only the first 80 characters of the value.

This prevents huge tokens from making the UI unreadable.

---

```python
"reason": c.reason
```

Why the value was flagged.

---

```python
return pd.DataFrame(rows)
```

Returns the table.

---

## 38. Main Streamlit app

```python
def main() -> None:
    import streamlit as st
```

The Streamlit import is inside `main()` so the rest of the file can still be imported or self-tested without Streamlit being loaded immediately.

---

```python
st.set_page_config(page_title="JMeter Auto-Correlation", layout="wide")
```

Sets browser/page settings.

---

```python
st.title("JMeter Auto-Correlation Generator")
```

Displays the app title.

---

```python
st.caption(...)
```

Shows a short description and app version.

---

### Limitation expander

```python
with st.expander("Important limitation", expanded=False):
    st.write(...)
```

Shows an expandable warning.

The important limitation is that a `.jmx` file usually contains recorded requests, not actual server responses. Therefore the app cannot know with certainty where a token came from. It guesses the extractor source as the previous HTTP sampler.

---

### Upload and sidebar controls

```python
uploaded = st.file_uploader("Upload JMeter .jmx file", type=["jmx", "xml"])
```

Lets the user upload a JMeter file.

---

```python
min_len = st.sidebar.slider("Minimum value length", min_value=6, max_value=32, value=8)
```

Lets the user control the minimum token length to consider.

---

```python
require_reuse = st.sidebar.checkbox("Only show values that appear in at least one request", value=True)
```

Adds a checkbox. As mentioned earlier, the current implementation does not filter much because every detected value appears at least once.

---

### No upload case

```python
if not uploaded:
    st.info("Upload a JMX file to start.")
    return
```

If no file is uploaded, the app stops here.

---

### Read uploaded file

```python
raw = uploaded.read()
```

Reads the uploaded file as bytes.

---

### Parse JMX

```python
try:
    tree, xml_fixes = parse_jmx(raw)
except ET.ParseError as exc:
```

Tries to parse the file.

If parsing fails, it shows useful diagnostics.

---

```python
cleaned_preview, fix_count = sanitize_jmx_xml(raw)
```

Even after failure, it creates a sanitized version for troubleshooting.

---

```python
st.error(...)
```

Shows an error in the UI.

---

```python
if fix_count:
    st.warning(...)
```

Warns if invalid XML characters were removed but another XML issue remains.

---

```python
diag_raw = describe_parse_position(raw, exc)
diag_clean = describe_parse_position(cleaned_preview, exc)
```

Creates error snippets for both the original and cleaned XML.

---

```python
if diag_raw:
    st.code(diag_raw, language="text")
```

Displays the raw parse-error context.

---

```python
if diag_clean and diag_clean != diag_raw:
    st.code("After sanitizer:\n" + diag_clean, language="text")
```

Displays sanitized parse-error context if different.

---

```python
st.download_button(
    "Download sanitized JMX for troubleshooting",
    data=cleaned_preview,
    file_name=uploaded.name.rsplit(".", 1)[0] + "_sanitized_for_debug.jmx",
    mime="application/xml",
)
```

Lets the user download the sanitized JMX for debugging.

---

```python
return
```

Stops the app because parsing failed.

---

### Warn about removed XML-invalid characters

```python
if xml_fixes:
    st.warning(...)
```

If the sanitizer removed invalid XML characters, the app warns the user.

This often happens when recorded binary/gzip/protobuf bodies were stored inside the JMX.

---

### Collect samplers and detect candidates

```python
samplers = collect_samplers(tree.getroot())
candidates = detect_candidates(samplers, min_length=min_len, require_reuse=require_reuse)
```

The app finds HTTP samplers and scans them for dynamic-looking values.

---

### Show metrics

```python
c1, c2 = st.columns(2)
c1.metric("HTTP samplers found", len(samplers))
c2.metric("Correlation candidates", len(candidates))
```

Shows two summary metrics.

---

### No candidates case

```python
if not candidates:
    st.warning(...)
    return
```

If nothing dynamic-looking was found, the app suggests reducing the minimum length or checking the JMX contents.

---

## 39. Candidate review UI

```python
st.subheader("Review candidates")
df = candidates_to_df(candidates, samplers)
```

Creates the candidate review table.

---

```python
edited = st.data_editor(
    df,
    width="stretch",
    hide_index=True,
    disabled=[...],
    column_config={...},
)
```

Displays an editable table.

The user can edit:

```text
selected/apply checkbox
source sampler
variable name
```

Most other columns are disabled.

---

```python
"selected": st.column_config.CheckboxColumn("Apply", default=True)
```

Creates an “Apply” checkbox.

---

```python
"id": None
```

Hides the internal ID column.

---

```python
"source_sampler": st.column_config.SelectboxColumn(
    "Extractor source sampler",
    options=[s.name for s in samplers]
)
```

Lets the user choose which sampler should receive the Regex Extractor.

---

```python
"variable": st.column_config.TextColumn("Variable name")
```

Lets the user edit the JMeter variable name.

---

## 40. Applying table edits back to candidates

```python
name_to_index = {s.name: s.index for s in samplers}
selected_ids: List[str] = []
source_overrides: Dict[str, int] = {}
```

Creates a map from sampler name to sampler index and prepares selected candidate data.

---

```python
for _, row in edited.iterrows():
```

Loops through edited table rows.

---

```python
cid = row["id"]
c = next(x for x in candidates if x.id == cid)
```

Finds the matching `Candidate` object.

---

```python
c.variable_name = re.sub(r"[^A-Za-z0-9_]", "_", str(row["variable"]).strip()) or c.variable_name
```

Sanitizes the edited variable name so it only contains letters, digits, and underscores.

If the user leaves it empty, the old variable name is kept.

---

```python
c.source_sampler_index = name_to_index.get(row["source_sampler"], c.source_sampler_index)
source_overrides[cid] = c.source_sampler_index
```

Stores the selected source sampler.

---

```python
if bool(row["selected"]):
    selected_ids.append(cid)
```

Tracks which candidates the user selected.

---

## 41. Showing extraction patterns

```python
st.subheader("Details")
with st.expander("Show extraction patterns"):
    for c in candidates:
        st.code(f"{c.variable_name}: {c.extraction_pattern}", language="text")
```

Displays all generated regex patterns in an expandable area.

This helps the user review and manually verify extraction logic.

---

## 42. Generate correlated JMX button

```python
if st.button("Generate correlated JMX", type="primary", disabled=not selected_ids):
```

Shows a button.

The button is disabled if no candidates are selected.

---

```python
try:
    fresh_tree, _ = parse_jmx(raw)
```

Re-parses the original uploaded file.

This avoids modifying the already parsed tree repeatedly during Streamlit reruns.

---

```python
new_bytes, added, replaced = apply_candidates(
    fresh_tree,
    candidates,
    selected_ids,
    source_overrides
)
```

Adds Regex Extractors and replaces hardcoded values.

---

```python
output_name = uploaded.name.rsplit(".", 1)[0] + "_correlated.jmx"
```

Creates the output file name.

Example:

```text
testplan.jmx -> testplan_correlated.jmx
```

---

```python
st.success(f"Generated file. Added {added} extractor(s), replaced {replaced} value occurrence(s).")
```

Shows a success message.

---

```python
st.download_button(
    "Download correlated JMX",
    data=new_bytes,
    file_name=output_name,
    mime="application/xml",
)
```

Lets the user download the modified JMX.

---

```python
except Exception as exc:
    st.exception(exc)
```

If something goes wrong, Streamlit displays the exception details.

---

## 43. Self-test function

```python
def run_self_test() -> None:
```

This is a small built-in test for the XML sanitizer/parser.

---

```python
sample = b'''<?xml version="1.0" encoding="UTF-8"?>
...
<stringProp name="Argument.value">&#x1f;abc&#x8;&#x0;&#31;&#55296;def</stringProp>
...
'''
```

The sample JMX contains invalid XML numeric references:

```text
&#x1f;
&#x8;
&#x0;
&#31;
&#55296;
```

Those should be removed.

---

```python
tree, fixes = parse_jmx(sample)
```

Parses the sample after sanitizing it.

---

```python
value = tree.find(".//stringProp[@name='Argument.value']")
```

Finds the argument value node.

---

```python
assert fixes >= 5, fixes
```

Checks that at least 5 invalid references were removed.

---

```python
assert value is not None
```

Checks that the value node exists.

---

```python
assert value.text == "abcdef", value.text
```

The original text was effectively:

```text
invalid abc invalid invalid invalid invalid def
```

After removing invalid references, it should become:

```text
abcdef
```

---

```python
print(f"{APP_VERSION}: self-test passed; removed {fixes} invalid XML character references.")
```

Prints a success message.

---

## 44. Script entry point

```python
if __name__ == "__main__":
    if "--self-test" in sys.argv:
        run_self_test()
    else:
        main()
```

This controls what happens when the file is run directly.

If run like this:

```bash
python app.py --self-test
```

it runs the self-test.

Otherwise:

```bash
python app.py
```

starts the Streamlit app logic.

Normally, for Streamlit, the app would be launched like:

```bash
streamlit run app.py
```

---

## Overall flow

The full app flow is:

```text
User uploads JMX
        ↓
Read raw bytes
        ↓
Sanitize invalid XML characters
        ↓
Parse XML
        ↓
Collect HTTP samplers
        ↓
Scan request params, body-ish fields, and headers
        ↓
Detect dynamic-looking values
        ↓
Build correlation candidates
        ↓
Show editable review table
        ↓
User selects candidates and source samplers
        ↓
Generate Regex Extractors
        ↓
Replace hardcoded values with ${VARIABLE}
        ↓
Write new JMX
        ↓
User downloads correlated JMX
```

---

## Important caveats in this code

There are a few behaviors worth knowing.

First, the app only has the `.jmx`, which usually contains requests, not actual response bodies. So it cannot truly know where a token came from. It guesses that the token should be extracted from the previous HTTP sampler.

Second, the `require_reuse` option currently does not really filter candidates. This line:

```python
if require_reuse and len(unique_idxs) < 1:
```

will almost never remove anything, because every detected candidate appears at least once. If the intended meaning is “show only reused values,” it should likely be:

```python
if require_reuse and len(unique_idxs) < 2:
```

Third, CSRF extraction patterns may produce either capture group 1 or capture group 2, but the JMeter template is always:

```text
$1$
```

So some generated CSRF regexes may need manual review.

Fourth, the detection is heuristic. It looks for values that “look dynamic,” but it can produce false positives and false negatives. The review table is important because the user should verify candidates before generating the final JMX.

Fifth, two imports are unused:

```python
html
asdict
```

The optional top-level `lxml` import is also mostly redundant because `lxml` is imported again inside `parse_jmx()`.

Overall, the code is a Streamlit-based JMeter correlation helper that focuses on making broken or dirty JMX XML parseable, detecting likely dynamic request values, and generating a modified JMX with Regex Extractors and JMeter variable replacements.
