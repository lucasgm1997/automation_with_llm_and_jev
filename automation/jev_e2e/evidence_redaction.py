"""Bounded diagnostic output with common credentials removed before storage."""

import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MASK = "<redacted>"
SECRET_KEYS = {"authorization", "proxyauthorization", "cookie", "setcookie", "cookies", "password", "passwd", "pwd", "secret", "clientsecret", "token", "accesstoken", "refreshtoken", "idtoken", "apikey", "xapikey", "credential", "credentials"}
KEY_PATTERN = r"(?:authorization|proxy.authorization|set.cookie|cookie|password|passwd|pwd|(?:access[_-]?|refresh[_-]?|id[_-]?)?token|(?:client[_-]?)?secret|(?:x[_-]?)?api[_-]?key)"


def sensitive(key):
    return re.sub(r"[^a-z]", "", str(key).lower()) in SECRET_KEYS


def clean_text(value, limit=8192):
    text = str(value)
    # VM/DDS startup messages can themselves contain service authentication URLs.
    text = re.sub(r'((?:https?|wss?)://[^/\s?#]+/)[A-Za-z0-9_-]{6,}=(?=/)', r'\1<vm-token>', text)
    text = re.sub(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", lambda m: m[1] + " " + MASK, text)
    def replace(match):
        quote = match[2][0] if match[2][0] in "\"'" else ""
        return match[1] + quote + MASK + quote
    text = re.sub(r'(?i)(["\']?' + KEY_PATTERN + r'["\']?\s*[:=]\s*)("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[^\s,;&}\]]+)', replace, text)
    return text if len(text) <= limit else text[:limit] + "…<truncated>"


def clean(value, depth=0):
    if depth > 12:
        return "<depth limit>"
    if isinstance(value, dict):
        return {str(k): MASK if sensitive(k) else clean(v, depth + 1) for k, v in list(value.items())[:100]}
    if isinstance(value, list):
        return [clean(v, depth + 1) for v in value[:100]]
    if isinstance(value, str):
        return clean_url(value) if value.startswith(("http://", "https://")) else clean_text(value)
    return value


def clean_url(value):
    try:
        parsed = urlsplit(value)
        netloc = parsed.netloc.rsplit("@", 1)[-1]
        query = urlencode([(k, MASK if sensitive(k) else clean_text(v)) for k, v in parse_qsl(parsed.query, keep_blank_values=True)])
        return clean_text(urlunsplit((parsed.scheme, netloc, parsed.path, query, "")))
    except ValueError:
        return "<invalid URL>"


def body_preview(raw, headers):
    if not isinstance(raw, list):
        return {"available": False}
    content_type = next((v for k, v in (headers or {}).items() if k.lower() == "content-type"), "")
    if isinstance(content_type, list):
        content_type = ";".join(content_type)
    output = {"available": True, "bytes": len(raw), "truncated": len(raw) > 8192}
    if content_type and not any(t in content_type.lower() for t in ("json", "text", "xml", "javascript", "form-urlencoded")):
        return {**output, "omitted": "binary or unsupported content type"}
    # Never emit a partially parsed JSON secret. Parse complete small bodies;
    # large bodies are omitted rather than returned without reliable redaction.
    if len(raw) > 32768:
        return {**output, "omitted": "body exceeds preview budget"}
    try:
        text = bytes(raw).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return {**output, "omitted": "non-UTF8 body"}
    try:
        text = json.dumps(clean(json.loads(text)), ensure_ascii=False)
    except ValueError:
        if "form-urlencoded" in content_type:
            text = urlencode([(k, MASK if sensitive(k) else clean_text(v)) for k, v in parse_qsl(text, keep_blank_values=True)])
    return {**output, "text": clean_text(text)}
