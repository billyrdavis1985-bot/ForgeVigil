"""Offline saved-email inspection. Facts and review signals, never a safety verdict.

No HTML rendering, URL lookup, attachment extraction/execution, model call or AV
scan occurs here. Existing request policy and receipt formats are untouched.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses
from html.parser import HTMLParser
from urllib.parse import urlsplit

from .versions import CODE_VERSION

FORMAT = "forgevigil.email-inspection.v1"
MAX_INPUT_BYTES = 5 * 1024 * 1024
MAX_HEADER_BYTES = 64 * 1024
MAX_PARTS = 100
MAX_DEPTH = 20
MAX_TEXT_CHARS = 65536
MAX_LINKS = 100
MAX_ATTACHMENTS = 25
MAX_URL_CHARS = 2048
MAX_NAME_CHARS = 200
_IS_WINDOWS = os.name == "nt"
_WEB_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_ACTIVE_SUFFIXES = frozenset({"exe", "com", "scr", "bat", "cmd", "ps1", "vbs", "vbe", "js", "jse", "wsf", "wsh", "hta", "lnk", "msi", "dll", "jar", "chm"})
_MACRO_SUFFIXES = frozenset({"docm", "xlsm", "pptm", "dotm", "xltm", "potm"})
_BIDI = frozenset("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


class EmailInspectionError(Exception):
    """Only a fixed reason code is safe to show at the command boundary."""


class _MimeLimit(Exception):
    pass


def input_path(value: Path) -> Path:
    windows = PureWindowsPath(value)
    parts = windows.parts[1:] if windows.anchor else windows.parts
    if _IS_WINDOWS and (str(windows).startswith(("\\\\.\\", "\\\\?\\")) or any(
        ":" in part or part.endswith((".", " ")) or PureWindowsPath(part).is_reserved()
        for part in parts if part != ".."
    )):
        raise EmailInspectionError("UNSUPPORTED_WINDOWS_INPUT_NAME")
    path = Path(os.path.abspath(value))
    if path.suffix.lower() != ".eml":
        raise EmailInspectionError("SAVED_EML_FILE_REQUIRED")
    try:
        for item in (path, *path.parents):
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise EmailInspectionError("INPUT_LINK_OR_REPARSE_POINT_REFUSED")
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise EmailInspectionError("REGULAR_INPUT_FILE_REQUIRED")
        if info.st_size > MAX_INPUT_BYTES:
            raise EmailInspectionError("EMAIL_INPUT_TOO_LARGE")
    except OSError:
        raise EmailInspectionError("EMAIL_INPUT_UNREADABLE") from None
    return path


def inspect_email(path: Path) -> dict:
    path = input_path(path)
    before = path.lstat()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    try:
        with os.fdopen(os.open(path, flags), "rb") as source:
            opened = os.fstat(source.fileno())
            if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise EmailInspectionError("EMAIL_INPUT_CHANGED")
            raw = source.read(MAX_INPUT_BYTES + 1)
            after = os.fstat(source.fileno())
            if (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or len(raw) != after.st_size:
                raise EmailInspectionError("EMAIL_INPUT_CHANGED")
    except OSError:
        raise EmailInspectionError("EMAIL_INPUT_UNREADABLE") from None
    if len(raw) > MAX_INPUT_BYTES:
        raise EmailInspectionError("EMAIL_INPUT_TOO_LARGE")
    return inspect_bytes(raw)


def _host(value: str | None) -> str | None:
    if not value:
        return None
    try:
        try:
            return ipaddress.ip_address(value.strip("[]")).compressed
        except ValueError:
            pass
        result = value.rstrip(".").encode("idna").decode("ascii").lower()
        if not result or len(result) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in result.split(".")):
            return None
        return result
    except (UnicodeError, ValueError):
        return None


def _domains(message, header, issues):
    try:
        headers = message.get_all(header, [])
        if len(headers) > 1:
            issues.add("DUPLICATE_ADDRESS_HEADER")
        domains = []
        for _, address in getaddresses([str(h) for h in headers]):
            domain = _host(address.rsplit("@", 1)[1]) if address.count("@") == 1 else None
            if domain is None:
                issues.add("INVALID_ADDRESS_HEADER")
            elif domain not in domains:
                domains.append(domain)
        if headers and not domains:
            issues.add("INVALID_ADDRESS_HEADER")
        return domains
    except (ValueError, IndexError, TypeError):
        issues.add("INVALID_ADDRESS_HEADER")
        return []


def _url_facts(value, issues):
    signals = []
    if len(value) > MAX_URL_CHARS:
        issues.add("URL_LENGTH_LIMIT")
        return {"scheme": None, "host": None, "signals": ["URL_NOT_INSPECTED"]}
    if any(ord(c) < 32 or ord(c) == 127 or c in _BIDI for c in value):
        signals.append("LINK_CONTROL_CHARACTERS")
    try:
        parts = urlsplit(value.strip())
        scheme = parts.scheme.lower()
        host = _host(parts.hostname)
        _ = parts.port  # malformed ports are incomplete, not silently ignored
        if scheme in ("http", "https") or value.startswith("//"):
            if host is None:
                issues.add("INVALID_WEB_URL")
            if parts.username is not None or parts.password is not None:
                signals.append("LINK_CONTAINS_USERINFO")
            try:
                ipaddress.ip_address(host or "")
            except ValueError:
                pass
            else:
                signals.append("LINK_USES_IP_ADDRESS")
        elif scheme not in ("", "mailto", "tel", "cid"):
            signals.append("LINK_ACTIVE_OR_UNSUPPORTED_SCHEME")
        if not scheme and not parts.netloc and value and not value.startswith("#"):
            issues.add("RELATIVE_LINK_DESTINATION_UNRESOLVED")
        return {"scheme": scheme or ("scheme-relative" if parts.netloc else "relative"), "host": host, "signals": signals}
    except (ValueError, UnicodeError):
        issues.add("INVALID_URL")
        return {"scheme": None, "host": None, "signals": ["URL_NOT_INSPECTED"]}


class _HtmlLinks(HTMLParser):
    def __init__(self, add, issues):
        super().__init__(convert_charrefs=True)
        self.add, self.issues = add, issues
        self.current = None
        self.text = []
        self.text_length = 0

    def finish_anchor(self):
        if self.current is not None:
            self.add(self.current, "".join(self.text), "html")
        self.current, self.text, self.text_length = None, [], 0

    def handle_starttag(self, tag, attrs):
        pairs = [(k.lower(), v) for k, v in attrs]
        if tag.lower() == "base":
            self.issues.add("HTML_BASE_NOT_RESOLVED")
        if tag.lower() == "a":
            if self.current is not None:
                self.issues.add("NESTED_HTML_ANCHOR")
                self.finish_anchor()
            values = [v for k, v in pairs if k == "href"]
            if len(values) > 1:
                self.issues.add("DUPLICATE_LINK_TARGET")
            self.current = values[0] if values and values[0] is not None else None
        if tag.lower() == "form":
            for k, v in pairs:
                if k == "action" and v:
                    self.add(v, "", "html-form")

    def handle_endtag(self, tag):
        if tag.lower() == "a":
            self.finish_anchor()

    def handle_data(self, data):
        if self.current is not None:
            if len(data) > 512 - self.text_length:
                self.issues.add("LINK_DISPLAY_TEXT_LIMIT")
            fragment = data[:max(0, 512 - self.text_length)]
            if fragment:
                self.text.append(fragment)
                self.text_length += len(fragment)


def _attachment(part, index, issues):
    name = part.get_filename()
    signals = []
    if name:
        if len(name) > MAX_NAME_CHARS:
            issues.add("ATTACHMENT_NAME_LIMIT")
        if any(c in name for c in ("/", "\\", ":")):
            signals.append("ATTACHMENT_PATH_LIKE_NAME")
        if any(c in _BIDI or ord(c) < 32 or ord(c) == 127 for c in name):
            signals.append("ATTACHMENT_CONTROL_CHARACTERS")
        if name.endswith((".", " ")) or PureWindowsPath(name).is_reserved():
            signals.append("ATTACHMENT_AMBIGUOUS_WINDOWS_NAME")
        suffix = name.rstrip(". ").rsplit(".", 1)[-1].lower() if "." in name else ""
        if suffix in _ACTIVE_SUFFIXES:
            signals.append("ATTACHMENT_ACTIVE_CONTENT_EXTENSION")
        if suffix in _MACRO_SUFFIXES:
            signals.append("ATTACHMENT_MACRO_CAPABLE_EXTENSION")
    payload = None if part.is_multipart() else part.get_payload(decode=True)
    if payload is None:
        issues.add("ATTACHMENT_BYTES_NOT_INSPECTED")
    return {"id": f"attachment-{index}", "filename": name[:MAX_NAME_CHARS] if name else None,
            "filename_truncated": bool(name and len(name) > MAX_NAME_CHARS),
            "media_type": part.get_content_type(), "bytes": len(payload) if payload is not None else None,
            "sha256": hashlib.sha256(payload).hexdigest() if payload is not None else None,
            "signals": signals, "scan_status": "not_scanned"}


def inspect_bytes(raw: bytes) -> dict:
    if len(raw) > MAX_INPUT_BYTES:
        raise EmailInspectionError("EMAIL_INPUT_TOO_LARGE")
    issues = set()
    report = {"format": FORMAT, "code_version": CODE_VERSION,
              "input": {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)},
              "scope": "offline structural signals; no phishing verdict or malware scan",
              "sender": {"from_domains": [], "reply_to_domains": [], "reply_domain_differs": False,
                         "authentication": "not_verified", "authentication_header_present": False},
              "links": [], "attachments": [],
              "assessments": {"model": "not_run", "antivirus": "not_run"}}
    def finish():
        findings = sum(len(item["signals"]) for group in ("links", "attachments") for item in report[group])
        report["inspection"] = {"status": "incomplete" if issues else "complete",
                                "issues": sorted(issues), "signal_count": findings,
                                "attention": "incomplete" if issues else "review_signals" if findings else "no_listed_signals"}
        return report
    separator = re.search(br"\r?\n\r?\n", raw)
    if separator is None:
        issues.add("MISSING_HEADER_SEPARATOR")
        return finish()
    if separator.start() > MAX_HEADER_BYTES:
        issues.add("HEADER_SIZE_LIMIT")
        return finish()
    try:
        parsed_parts = 0
        def bounded_message(*args, **kwargs):
            nonlocal parsed_parts
            parsed_parts += 1
            if parsed_parts > MAX_PARTS:
                raise _MimeLimit
            return EmailMessage(*args, **kwargs)
        message = BytesParser(policy=policy.default.clone(message_factory=bounded_message)).parsebytes(raw)
        report["sender"]["from_domains"] = _domains(message, "From", issues)
        report["sender"]["reply_to_domains"] = _domains(message, "Reply-To", issues)
        if not report["sender"]["from_domains"]:
            issues.add("MISSING_OR_INVALID_FROM")
        report["sender"]["reply_domain_differs"] = bool(report["sender"]["reply_to_domains"] and
            set(report["sender"]["reply_to_domains"]) != set(report["sender"]["from_domains"]))
        report["sender"]["authentication_header_present"] = bool(message.get_all("Authentication-Results"))
        seen_links = set()
        def add_link(target, displayed, source):
            shown = _WEB_URL.search(displayed.strip())
            shown_host = _url_facts(shown.group(0), issues)["host"] if shown else None
            key = (target, shown_host)
            if key in seen_links:
                return
            if len(report["links"]) >= MAX_LINKS:
                issues.add("LINK_COUNT_LIMIT")
                return
            seen_links.add(key)
            fact = _url_facts(target, issues)
            fact.update(id=f"link-{len(report['links']) + 1}", source=source, displayed_host=shown_host)
            if shown_host and fact["host"] and shown_host != fact["host"]:
                fact["signals"].append("LINK_DISPLAY_HOST_DIFFERS")
            if source == "html-form":
                fact["signals"].append("EMAIL_FORM_ACTION")
            report["links"].append(fact)
        pending, count, text_used = [(message, 0)], 0, 0
        while pending:
            part, depth = pending.pop()
            count += 1
            if count > MAX_PARTS or depth > MAX_DEPTH:
                issues.add("MIME_STRUCTURE_LIMIT")
                break
            is_attachment = part.get_content_disposition() == "attachment" or part.get_filename() is not None
            if is_attachment or (not part.is_multipart() and part.get_content_type() not in ("text/plain", "text/html")):
                if len(report["attachments"]) >= MAX_ATTACHMENTS:
                    issues.add("ATTACHMENT_COUNT_LIMIT")
                else:
                    report["attachments"].append(_attachment(part, len(report["attachments"]) + 1, issues))
            elif part.is_multipart():
                pending.extend((child, depth + 1) for child in reversed(part.get_payload()))
            else:
                payload = part.get_payload(decode=True)
                if payload is None:
                    issues.add("BODY_NOT_DECODED")
                    continue
                try:
                    text = payload.decode(part.get_content_charset() or "ascii")
                except (LookupError, UnicodeError):
                    issues.add("BODY_ENCODING_INVALID")
                    text = payload.decode("utf-8", errors="replace")
                room = max(0, MAX_TEXT_CHARS - text_used)
                if len(text) > room:
                    issues.add("BODY_TEXT_LIMIT")
                    text = text[:room]
                text_used += len(text)
                if part.get_content_type() == "text/html":
                    parser = _HtmlLinks(add_link, issues)
                    parser.feed(text)
                    parser.close()
                    if parser.current is not None:
                        issues.add("UNCLOSED_HTML_ANCHOR")
                        parser.finish_anchor()
                else:
                    for match in _WEB_URL.finditer(text):
                        add_link(match.group(0).rstrip(".,;!?)]}"), "", "plain-text")
            if part.defects:
                issues.add("MIME_PARSE_DEFECT")
    except _MimeLimit:
        issues.add("MIME_STRUCTURE_LIMIT")
    except (ValueError, TypeError, IndexError, RecursionError, UnicodeError):
        issues.add("EMAIL_PARSE_FAILED")
    return finish()


def format_report(report: dict) -> str:
    inspection = report["inspection"]
    shown = lambda value: json.dumps(value, ensure_ascii=True)
    lines = ["ForgeVigil saved-email inspection (offline)",
             "Inspection: " + inspection["status"] + "; attention: " + inspection["attention"],
             "Model assessment: not run; attachment antivirus: not run.",
             "Input SHA256: " + report["input"]["sha256"],
             "From domains: " + shown(report["sender"]["from_domains"]),
             "Reply-To domains: " + shown(report["sender"]["reply_to_domains"]),
             "Sender authentication: not verified; supplied headers are untrusted claims."]
    if report["sender"]["reply_domain_differs"]:
        lines.append("Context: Reply-To and From domains differ; legitimate services can do this.")
    for link in report["links"]:
        lines.append(f"{link['id']}: actual host {shown(link['host'])}; displayed host {shown(link['displayed_host'])}; "
                     f"scheme {shown(link['scheme'])}; signals {shown(link['signals'])}")
    for attachment in report["attachments"]:
        lines.append(f"{attachment['id']}: name {shown(attachment['filename'])}; bytes {attachment['bytes']}; "
                     f"scan not performed; signals {shown(attachment['signals'])}")
    if inspection["issues"]:
        lines.append("Incomplete: " + ", ".join(inspection["issues"]))
    lines.append("Signals need human review; legitimate mail can trigger them. No listed signals does not establish safety.")
    return "\n".join(lines)
