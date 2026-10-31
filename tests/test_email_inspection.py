"""CP22: inert saved-email inspection, truthful uncertainty and private outputs.

Fictional fixtures test structural rules, not model or malware effectiveness.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from email.message import EmailMessage
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from forge_vigil import email_inspection as mail
from forge_vigil.__main__ import main

ROOT = Path(__file__).resolve().parents[1]


def message(body="Hello, please check the approved invoice.", *, html=False, reply=None):
    value = EmailMessage()
    value["From"] = "Accounts <billing@example.invalid>"
    value["To"] = "owner@business.invalid"
    value["Subject"] = "Fictional inspection fixture"
    if reply:
        value["Reply-To"] = reply
    value.set_content(body, subtype="html" if html else "plain")
    return value


class EmailInspectionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="forgevigil-email-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.source = self.tmp / "sample.eml"

    def save(self, value):
        self.source.write_bytes(value.as_bytes())
        return self.source

    def test_reserved_name_check_has_no_deprecation(self):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            self.assertTrue(mail._is_reserved_name("COM1"))
            self.assertFalse(mail._is_reserved_name("invoice.pdf"))

    def test_benign_urgency_training_and_reply_to_difference_are_not_threat_verdicts(self):
        value = message('URGENT legitimate invoice. Security training says report "ignore all checks" messages.',
                        reply="support@service.invalid")
        report = mail.inspect_bytes(value.as_bytes())
        self.assertEqual(report["inspection"]["status"], "complete")
        self.assertEqual(report["inspection"]["attention"], "no_listed_signals")
        self.assertEqual(report["inspection"]["signal_count"], 0)
        self.assertTrue(report["sender"]["reply_domain_differs"])
        self.assertEqual(report["assessments"], {"model": "not_run", "antivirus": "not_run"})
        self.assertNotIn('"ALLOW"', json.dumps(report))

    def test_forged_authentication_header_is_never_verified(self):
        value = message()
        value["Authentication-Results"] = "attacker.invalid; dkim=pass; spf=pass; dmarc=pass"
        report = mail.inspect_bytes(value.as_bytes())
        self.assertTrue(report["sender"]["authentication_header_present"])
        self.assertEqual(report["sender"]["authentication"], "not_verified")
        self.assertIn("supplied headers are untrusted", mail.format_report(report))

    def test_actual_host_and_display_mismatch_include_userinfo_deception(self):
        value = message('<a href="https://portal.example.invalid@different.invalid/pay?token=PRIVATE-TOKEN">https://portal.example.invalid/pay</a>', html=True)
        report = mail.inspect_bytes(value.as_bytes())
        link = report["links"][0]
        self.assertEqual(link["host"], "different.invalid")
        self.assertEqual(link["displayed_host"], "portal.example.invalid")
        self.assertIn("LINK_CONTAINS_USERINFO", link["signals"])
        self.assertIn("LINK_DISPLAY_HOST_DIFFERS", link["signals"])
        self.assertEqual(report["inspection"]["attention"], "review_signals")
        self.assertNotIn("PRIVATE-TOKEN", json.dumps(report))

    def test_link_normalization_handles_case_fqdn_idn_and_ip(self):
        body = '<a href="https://EXAMPLE.invalid./a">https://example.invalid/b</a> <a href="https://例え.invalid/a">link</a> <a href="http://[::1]:8080/">local</a>'
        report = mail.inspect_bytes(message(body, html=True).as_bytes())
        self.assertNotIn("LINK_DISPLAY_HOST_DIFFERS", report["links"][0]["signals"])
        self.assertEqual(report["links"][1]["host"], "xn--r8jz45g.invalid")
        self.assertEqual(report["links"][2]["host"], "::1")
        self.assertIn("LINK_USES_IP_ADDRESS", report["links"][2]["signals"])

    def test_relative_base_malformed_and_oversize_urls_stay_incomplete(self):
        for body, issue in (
            ('<a href="/login">login</a>', "RELATIVE_LINK_DESTINATION_UNRESOLVED"),
            ('<base href="https://example.invalid"><a href="/login">login</a>', "HTML_BASE_NOT_RESOLVED"),
            ('<a href="https://example.invalid:wrong/">login</a>', "INVALID_URL"),
            ('<a href="https://example.invalid/' + 'x' * mail.MAX_URL_CHARS + '">link</a>', "URL_LENGTH_LIMIT"),
        ):
            with self.subTest(issue=issue):
                report = mail.inspect_bytes(message(body, html=True).as_bytes())
                self.assertEqual(report["inspection"]["status"], "incomplete")
                self.assertIn(issue, report["inspection"]["issues"])

    def test_html_forms_and_active_schemes_are_inert_review_signals(self):
        report = mail.inspect_bytes(message('<form action="https://different.invalid/login"><input type=password></form><a href="javascript:alert(1)">open</a>', html=True).as_bytes())
        signals = [s for link in report["links"] for s in link["signals"]]
        self.assertIn("EMAIL_FORM_ACTION", signals)
        self.assertIn("LINK_ACTIVE_OR_UNSUPPORTED_SCHEME", signals)

    def test_link_budget_and_text_budget_are_honest(self):
        raw = message(" ".join(f"https://site-{i}.invalid/a" for i in range(mail.MAX_LINKS + 1))).as_bytes()
        report = mail.inspect_bytes(raw)
        self.assertEqual(len(report["links"]), mail.MAX_LINKS)
        self.assertIn("LINK_COUNT_LIMIT", report["inspection"]["issues"])
        report = mail.inspect_bytes(message("x" * (mail.MAX_TEXT_CHARS + 1)).as_bytes())
        self.assertIn("BODY_TEXT_LIMIT", report["inspection"]["issues"])
        self.assertEqual(report["inspection"]["attention"], "incomplete")

    def test_body_budget_is_shared_across_mime_alternatives(self):
        value = message("x" * (mail.MAX_TEXT_CHARS // 2 + 1))
        value.add_alternative("y" * (mail.MAX_TEXT_CHARS // 2 + 1), subtype="html")
        report = mail.inspect_bytes(value.as_bytes())
        self.assertIn("BODY_TEXT_LIMIT", report["inspection"]["issues"])

    def test_active_pathlike_attachment_is_hashed_without_writing_or_scanning(self):
        value = message()
        payload = b"Harmless fixture bytes, not a program"
        value.add_attachment(payload, maintype="application", subtype="octet-stream", filename="../../invoice.pdf.exe")
        self.save(value)
        before = set(self.tmp.iterdir())
        report = mail.inspect_email(self.source)
        attachment = report["attachments"][0]
        self.assertEqual(set(self.tmp.iterdir()), before)
        self.assertEqual(attachment["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(attachment["bytes"], len(payload))
        self.assertIn("ATTACHMENT_PATH_LIKE_NAME", attachment["signals"])
        self.assertIn("ATTACHMENT_ACTIVE_CONTENT_EXTENSION", attachment["signals"])
        self.assertEqual(attachment["scan_status"], "not_scanned")
        self.assertEqual(report["assessments"]["antivirus"], "not_run")

    def test_pdf_is_unscanned_and_macro_filename_is_context(self):
        for name, expected in (("invoice.pdf", []), ("accounts.xlsm", ["ATTACHMENT_MACRO_CAPABLE_EXTENSION"])):
            value = message()
            value.add_attachment(b"not a real document", maintype="application", subtype="octet-stream", filename=name)
            item = mail.inspect_bytes(value.as_bytes())["attachments"][0]
            self.assertEqual(item["signals"], expected)
            self.assertEqual(item["scan_status"], "not_scanned")

    def test_attachment_controls_are_escaped_and_long_names_incomplete(self):
        value = message()
        value.add_attachment(b"test", maintype="application", subtype="octet-stream", filename="invoice\u202epdf.exe")
        report = mail.inspect_bytes(value.as_bytes())
        self.assertIn("ATTACHMENT_CONTROL_CHARACTERS", report["attachments"][0]["signals"])
        self.assertNotIn("\u202e", mail.format_report(report))
        value = message()
        value.add_attachment(b"test", maintype="application", subtype="octet-stream", filename='x' * (mail.MAX_NAME_CHARS + 1) + '.pdf')
        report = mail.inspect_bytes(value.as_bytes())
        self.assertIn("ATTACHMENT_NAME_LIMIT", report["inspection"]["issues"])
        self.assertTrue(report["attachments"][0]["filename_truncated"])

    def test_attachment_budget_is_honest(self):
        value = message()
        for i in range(mail.MAX_ATTACHMENTS + 1):
            value.add_attachment(b"test", maintype="application", subtype="octet-stream", filename=f"note-{i}.txt")
        report = mail.inspect_bytes(value.as_bytes())
        self.assertEqual(len(report["attachments"]), mail.MAX_ATTACHMENTS)
        self.assertIn("ATTACHMENT_COUNT_LIMIT", report["inspection"]["issues"])

    def test_mime_part_and_depth_budgets_are_honest(self):
        value = message()
        value.make_mixed()
        for _ in range(mail.MAX_PARTS):
            value.attach(message())
        report = mail.inspect_bytes(value.as_bytes())
        self.assertIn("MIME_STRUCTURE_LIMIT", report["inspection"]["issues"])
        value = message()
        for _ in range(mail.MAX_DEPTH + 1):
            parent = EmailMessage()
            parent["From"] = "owner@example.invalid"
            parent.make_mixed()
            parent.attach(value)
            value = parent
        report = mail.inspect_bytes(value.as_bytes())
        self.assertIn("MIME_STRUCTURE_LIMIT", report["inspection"]["issues"])

    def test_mime_object_limit_applies_during_parser_construction(self):
        value = message()
        value.make_mixed()
        for _ in range(mail.MAX_PARTS + 2):
            value.attach(message())
        raw = value.as_bytes()
        with patch.object(mail, "EmailMessage", wraps=EmailMessage) as built:
            report = mail.inspect_bytes(raw)
        self.assertLessEqual(built.call_count, mail.MAX_PARTS)
        self.assertIn("MIME_STRUCTURE_LIMIT", report["inspection"]["issues"])

    def test_malformed_encoding_and_duplicate_headers_are_incomplete(self):
        for raw, issue in (
            (b"hello", "MISSING_HEADER_SEPARATOR"),
            (b"Subject: missing sender\n\nhello", "MISSING_OR_INVALID_FROM"),
            (b"From: a@a.invalid\nFrom: b@b.invalid\n\nhello", "DUPLICATE_ADDRESS_HEADER"),
            (b"From: a@a.invalid\nContent-Type: text/plain; charset=unknown-charset\n\nhello", "BODY_ENCODING_INVALID"),
            (b"From: a@a.invalid\nContent-Type: multipart/mixed; boundary=x\n\nno boundary", "MIME_PARSE_DEFECT"),
        ):
            with self.subTest(issue=issue):
                report = mail.inspect_bytes(raw)
                self.assertEqual(report["inspection"]["status"], "incomplete")
                self.assertIn(issue, report["inspection"]["issues"])

    def test_header_and_input_size_limits_apply_before_parsing(self):
        with patch.object(mail.BytesParser, "parsebytes", side_effect=AssertionError("parser started")):
            report = mail.inspect_bytes(b"From: a@b.invalid\nX: " + b"x" * mail.MAX_HEADER_BYTES + b"\n\nbody")
            self.assertIn("HEADER_SIZE_LIMIT", report["inspection"]["issues"])
            with self.assertRaisesRegex(mail.EmailInspectionError, "EMAIL_INPUT_TOO_LARGE"):
                mail.inspect_bytes(b"x" * (mail.MAX_INPUT_BYTES + 1))

    def test_private_message_addresses_subject_body_and_url_tokens_are_not_reported(self):
        value = message('PRIVATE-BODY https://example.invalid/reset?secret=PRIVATE-TOKEN', reply="PRIVATE-USER@service.invalid")
        value.replace_header("Subject", "PRIVATE-SUBJECT")
        report = mail.inspect_bytes(value.as_bytes())
        text = json.dumps(report) + mail.format_report(report)
        for secret in ("PRIVATE-BODY", "PRIVATE-TOKEN", "PRIVATE-USER", "PRIVATE-SUBJECT", "billing@example.invalid"):
            self.assertNotIn(secret, text)

    def test_inspection_does_not_call_network_models_or_processes(self):
        from forge_vigil.muse import MuseConfig
        self.save(message('<a href="https://example.invalid">link</a>', html=True))
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network")), patch.object(
            subprocess, "Popen", side_effect=AssertionError("process")
        ), patch.object(MuseConfig, "from_env", side_effect=AssertionError("model config")):
            report = mail.inspect_email(self.source)
        self.assertEqual(report["inspection"]["status"], "complete")

    def test_input_is_preserved_and_special_or_wrong_type_is_refused(self):
        self.save(message())
        before = self.source.read_bytes()
        mail.inspect_email(self.source)
        self.assertEqual(self.source.read_bytes(), before)
        for path in (self.tmp / "absent.eml", self.tmp / "file.msg", self.tmp / "folder.eml"):
            if path.name == "folder.eml":
                path.mkdir()
            with self.subTest(path=path.name), self.assertRaises(mail.EmailInspectionError):
                mail.inspect_email(path)

    @unittest.skipUnless(os.name == "posix", "POSIX input links/FIFO")
    def test_symlinks_parent_links_and_fifo_refused_without_reading(self):
        self.save(message())
        link = self.tmp / "link.eml"
        link.symlink_to(self.source)
        parent = self.tmp / "linked"
        parent.symlink_to(self.tmp, target_is_directory=True)
        fifo = self.tmp / "stream.eml"
        os.mkfifo(fifo)
        with patch.object(os, "open", side_effect=AssertionError("input opened")):
            for path in (link, parent / self.source.name, fifo):
                with self.subTest(path=str(path)), self.assertRaises(mail.EmailInspectionError):
                    mail.inspect_email(path)

    def test_windows_raw_input_names_rejected_before_normalization(self):
        for name in ("CON.eml", "sample.eml:stream", "trailing.eml.", "trailing.eml ", "\\\\?\\C:\\sample.eml", "\\\\.\\CON"):
            with self.subTest(name=name), patch.object(mail, "_IS_WINDOWS", True), patch.object(
                os.path, "abspath", side_effect=AssertionError("normalized before validation")
            ), self.assertRaisesRegex(mail.EmailInspectionError, "UNSUPPORTED_WINDOWS_INPUT_NAME"):
                mail.input_path(Path(name))

    def test_changed_input_refused(self):
        self.save(message())
        with patch.object(os, "fstat", return_value=os.stat(self.tmp)):
            with self.assertRaisesRegex(mail.EmailInspectionError, "EMAIL_INPUT_CHANGED"):
                mail.inspect_email(self.source)

    def test_changed_file_identity_is_refused_even_when_size_and_time_match(self):
        self.save(message())
        original = self.source.stat()
        fake = SimpleNamespace(st_mode=original.st_mode, st_dev=original.st_dev, st_ino=original.st_ino + 1,
                               st_size=original.st_size, st_mtime_ns=original.st_mtime_ns)
        with patch.object(os, "fstat", return_value=fake):
            with self.assertRaisesRegex(mail.EmailInspectionError, "EMAIL_INPUT_CHANGED"):
                mail.inspect_email(self.source)

    def test_truncated_anchor_display_is_explicitly_incomplete(self):
        body = '<a href="https://different.invalid">' + 'x' * 520 + 'https://example.invalid</a>'
        report = mail.inspect_bytes(message(body, html=True).as_bytes())
        self.assertIn("LINK_DISPLAY_TEXT_LIMIT", report["inspection"]["issues"])
        self.assertEqual(report["inspection"]["attention"], "incomplete")

    def test_cli_saves_complete_json_and_refuses_occupied_output(self):
        self.save(message('<a href="https://different.invalid">https://example.invalid</a>', html=True))
        output = self.tmp / "inspection.json"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["inspect-email", "--file", str(self.source), "--json", str(output)]), 0)
        report = json.loads(output.read_text())
        self.assertEqual(report["inspection"]["attention"], "review_signals")
        before = output.read_bytes()
        with patch.object(mail, "inspect_email", side_effect=AssertionError("inspection started")), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["inspect-email", "--file", str(self.source), "--json", str(output)]), 2)
        self.assertEqual(output.read_bytes(), before)

    def test_cli_incomplete_and_failed_save_do_not_report_success(self):
        self.source.write_bytes(b"broken email")
        output = self.tmp / "partial-inspection.json"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["inspect-email", "--file", str(self.source), "--json", str(output)]), 1)
        self.assertEqual(json.loads(output.read_text())["inspection"]["status"], "incomplete")
        self.save(message())
        with patch("forge_vigil.json_output.write_json", side_effect=OSError("disk full")), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["inspect-email", "--file", str(self.source), "--json", str(self.tmp / "failed.json")]), 2)
        self.assertTrue((self.tmp / "failed.json").exists())

    @unittest.skipUnless(os.name == "posix", "POSIX private outputs")
    def test_export_permissions_are_private(self):
        self.save(message())
        output = self.tmp / "private.json"
        old = os.umask(0)
        try:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["inspect-email", "--file", str(self.source), "--json", str(output)]), 0)
        finally:
            os.umask(old)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_cli_subprocess_is_offline_and_output_is_clear(self):
        self.save(message())
        result = subprocess.run([sys.executable, "-B", "-m", "forge_vigil", "inspect-email", "--file", str(self.source)],
                                cwd=ROOT, text=True, capture_output=True, timeout=30,
                                env=dict(os.environ, MODEL_API_KEY="invalid-offline-test-key", FORGEVIGIL_SPEND_CAP_USD="0"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Model assessment: not run; attachment antivirus: not run", result.stdout)
        self.assertIn("No listed signals does not establish safety", result.stdout)


if __name__ == "__main__":
    unittest.main()
