from __future__ import annotations

import re
from typing import List, Tuple

APP_VERSION = "v5-byte-cleaner-2026-06-03"

DYNAMIC_NAME_PATTERNS: List[Tuple[str, str]] = [
    (r"(?i)^(j?sessionid|session_id|sid|phpsessid|aspsessionid)$", "SESSION_ID"),
    (r"(?i)(csrf|_csrf|csrf_token|_token|authenticity_token|requestverificationtoken|antiforgery)", "CSRF_TOKEN"),
    (r"(?i)(__viewstate|__eventvalidation)", "VIEWSTATE"),
    (r"(?i)(access_token|refresh_token|id_token|auth_token|jwt|bearer|samlresponse|samlrequest|relaystate)", "AUTH_TOKEN"),
    (r"(?i)(nonce|_nonce|wp_nonce|security)", "NONCE"),
    (r"(?i)(timestamp|_timestamp|ts|_ts|time)$", "TIMESTAMP"),
    (r"(?i)(x-correlation-id|correlation-id|request-id|trace-id|x-request-id|x-trace-id)", "CORRELATION_ID"),
    (r"(?i)(api_key|apikey|x-api-key)", "CUSTOM"),
    (r"(?i)(transaction_id|order_id|invoice_id)", "CUSTOM"),
]

JWT_RE = re.compile(r"^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
LONG_TOKEN_RE = re.compile(r"^[A-Za-z0-9_./+=:-]{12,512}$")
XML_DECL_RE = re.compile(br"^\s*<\?xml[^>]*encoding=['\"]([^'\"]+)['\"]", re.I)
NUMERIC_CHAR_REF_RE = re.compile(r"&#(?:(?:[xX]([0-9A-Fa-f]+))|(\d+));?")
NUMERIC_CHAR_REF_BYTES_RE = re.compile(br"&#(?:(?:[xX]([0-9A-Fa-f]+))|(\d+));?")
