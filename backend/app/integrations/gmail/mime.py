"""Normalize Gmail full payloads without rendering HTML or downloading files."""
import base64
import binascii
from email.header import decode_header, make_header
from email.message import Message
from email.utils import getaddresses

MAX_BODY_BYTES = 10 * 1024 * 1024
MAX_PARTS = 1000
MAX_DEPTH = 30


class InvalidMessage(ValueError):
    pass


def provider_id(value):
    if not isinstance(value, str) or not value or len(value) > 128:
        raise InvalidMessage("invalid_provider_id")
    return value


def header_text(value):
    try:
        return str(make_header(decode_header(value)))
    except (LookupError, UnicodeError):
        return value


def normalize_message(message: dict, load_body=None) -> dict:
    payload = message.get("payload") or {}
    headers = [{"name": item["name"], "value": item["value"]} for item in payload.get("headers", [])]
    def values(name):
        return [header_text(item["value"]) for item in headers if item["name"].lower() == name]
    def recipients(name):
        return [{"name": name, "email": email} for name, email in getaddresses(values(name)) if email]

    plain, html, attachments = [], [], []
    body_bytes = 0
    parts_seen = 0
    def walk(part, path, depth):
        nonlocal body_bytes, parts_seen
        parts_seen += 1
        if parts_seen > MAX_PARTS or depth > MAX_DEPTH:
            raise InvalidMessage("mime_structure_limit")
        mime = part.get("mimeType", "application/octet-stream").lower()
        info = Message()
        for item in part.get("headers", []):
            info[item["name"]] = item["value"]
        body = part.get("body") or {}
        filename = part.get("filename") or ""
        attachment_id = body.get("attachmentId")
        is_text_body = mime in ("text/plain", "text/html") and not filename and info.get_content_disposition() != "attachment"
        if is_text_body:
            encoded = body.get("data")
            if not encoded and attachment_id:
                if load_body is None:
                    raise InvalidMessage("missing_text_body_loader")
                encoded = load_body(attachment_id)
            if encoded:
                if len(encoded) > (MAX_BODY_BYTES - body_bytes) * 4 // 3 + 8:
                    raise InvalidMessage("body_size_limit")
                try:
                    raw = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
                except (binascii.Error, ValueError):
                    raise InvalidMessage("invalid_body_encoding") from None
                body_bytes += len(raw)
                if body_bytes > MAX_BODY_BYTES:
                    raise InvalidMessage("body_size_limit")
                charset = info.get_content_charset() or "utf-8"
                try:
                    decoded = raw.decode(charset, errors="replace")
                except LookupError:
                    decoded = raw.decode("utf-8", errors="replace")
                (plain if mime == "text/plain" else html).append(decoded)
        elif filename or attachment_id or info.get_content_disposition() == "attachment" or (
            not mime.startswith("multipart/") and (body.get("data") or info.get("Content-ID"))
        ):
            size = int(body.get("size", 0))
            if size < 0:
                raise InvalidMessage("invalid_attachment_size")
            attachments.append({"mime_part_id": provider_id(part.get("partId") or path),
                                "gmail_attachment_id": attachment_id, "filename": filename,
                                "mime_type": mime, "size_bytes": size, "content_id": info.get("Content-ID")})
            # Attached messages/containers belong to the attachment, not the body.
            return
        for index, child in enumerate(part.get("parts", [])):
            walk(child, f"{path}.{index}", depth + 1)
    walk(payload, "0", 0)
    internal_date = int(message["internalDate"])
    size = int(message.get("sizeEstimate", 0))
    if internal_date < 0 or size < 0:
        raise InvalidMessage("invalid_message_size_or_date")
    return {"gmail_message_id": provider_id(message["id"]),
            "gmail_thread_id": provider_id(message["threadId"]),
            "gmail_history_id": message.get("historyId"), "internal_date": internal_date,
            "size_estimate": size, "from_address": ", ".join(values("from")),
            "to_addresses": recipients("to"), "cc_addresses": recipients("cc"), "bcc_addresses": recipients("bcc"),
            "subject": (values("subject") or [""])[0], "snippet": message.get("snippet", ""), "headers": headers,
            "body_text": "\n".join(plain) or None, "body_html": "\n".join(html) or None,
            "labels": sorted({provider_id(value) for value in message.get("labelIds", [])}),
            "attachments": attachments}
