"""Gizli bilgileri maskeleyen log yapılandırması."""
from __future__ import annotations

import logging
import re

_PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"), r"\1***"),
    (re.compile(r"(?i)((?:api[_-]?key|token|secret|password|authorization|x-api-key|xi-api-key)[\"'\s:=]+)([^\s\"',}&]+)"), r"\1***"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{10,}"), "sk-***"),
    (re.compile(r"(?i)(key\s+)[A-Za-z0-9:_\-]{16,}"), r"\1***"),
]


def redact(text: str) -> str:
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        record.msg = redact(msg)
        record.args = ()
        return True


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if any(isinstance(f, RedactFilter) for h in root.handlers for f in h.filters):
        return
    if not root.handlers:
        logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for h in root.handlers:
        h.addFilter(RedactFilter())
    root.setLevel(level)
