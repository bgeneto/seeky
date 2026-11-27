"""E-mail renderer (RFC 5322 / MIME, synthetic addresses only)."""

from __future__ import annotations

from email.utils import format_datetime

from .. import derive
from ..canonical import Document
from ..derive import parse_iso_utc
from .html import render_html


def _html_fragment(doc: Document) -> str:
    raw = render_html(doc).decode("utf-8")
    start = raw.index("<body>") + len("<body>")
    end = raw.index("</body>")
    return raw[start:end].strip()


def render_eml(doc: Document) -> bytes:
    boundary = "sdc-" + derive.digest_hex("sdc-eml", "boundary", doc.doc_id)[:24]
    message_id = derive.uuid4_like("sdc-eml-message-id", doc.doc_id)
    date = format_datetime(parse_iso_utc(doc.modified_at), usegmt=True)
    subject = doc.title.replace("\r", " ").replace("\n", " ")
    plain = doc.text
    html = _html_fragment(doc)
    lines = [
        'From: "SDC Synthetic Sender" <sender@example.com>',
        'To: "SDC Synthetic Recipient" <recipient@example.org>',
        f"Subject: {subject}",
        f"Date: {date}",
        f"Message-ID: <{message_id}@example.invalid>",
        "MIME-Version: 1.0",
        f'Content-Type: multipart/alternative; boundary="{boundary}"',
        "",
        "This is a multi-part message in MIME format.",
        "",
        f"--{boundary}",
        "Content-Type: text/plain; charset=utf-8",
        "Content-Transfer-Encoding: 8bit",
        "",
        plain,
        "",
        f"--{boundary}",
        "Content-Type: text/html; charset=utf-8",
        "Content-Transfer-Encoding: 8bit",
        "",
        "<html><body>",
        html,
        "</body></html>",
        "",
        f"--{boundary}--",
        "",
    ]
    return "\n".join(lines).encode("utf-8")
