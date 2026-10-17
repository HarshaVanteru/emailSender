"""Small outbound HTML allowlist; no executable markup or remote image loads."""
import base64
import re
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit

TAGS = set("p div br span b strong i em u s strike blockquote pre code ul ol li h1 h2 h3 a img font hr".split())
VOID = {"br", "img", "hr"}
BLOCKED = {"script", "style", "iframe", "object", "svg", "math", "template"}
IMAGE = re.compile(r"data:image/(png|jpeg|gif|webp);base64,([A-Za-z0-9+/=]+)")
STYLES = {"color", "background-color", "font-family", "font-size", "font-weight", "font-style", "text-decoration", "text-align", "margin-left", "max-width", "height"}


class CleanHTML(HTMLParser):
    def __init__(self, inline_images=False):
        super().__init__(convert_charrefs=True)
        self.output = []
        self.blocked = []
        self.images = []
        self.inline_images = inline_images

    def handle_starttag(self, tag, attrs):
        if tag in BLOCKED:
            self.blocked.append(tag)
            return
        if self.blocked or tag not in TAGS:
            return
        safe = []
        for key, value in attrs:
            value = value or ""
            if key == "style":
                rules = []
                for rule in value.split(";"):
                    name, _, content = rule.partition(":")
                    if name.strip().lower() in STYLES and not re.search(r"url|expression", content, re.I) and re.fullmatch(r"[A-Za-z0-9 #(),.%'\"_-]+", content.strip()):
                        rules.append(f"{name.strip().lower()}:{content.strip()}")
                if rules:
                    safe.append(("style", ";".join(rules)))
            elif tag == "a" and key == "href":
                if urlsplit(value).scheme.lower() in {"http", "https", "mailto"}:
                    safe.append((key, value))
            elif tag == "img" and key == "src":
                match = IMAGE.fullmatch(value)
                if match:
                    binary = base64.b64decode(match[2], validate=True)
                    if len(binary) > 5 * 1024 * 1024:
                        raise ValueError("Inline images must be 5 MB or smaller.")
                    if self.inline_images:
                        cid = f"image-{len(self.images)}@email-studio"
                        self.images.append((cid, match[1], binary))
                        value = f"cid:{cid}"
                    safe.append((key, value))
                elif re.fullmatch(r"cid:[A-Za-z0-9@._+-]+", value):
                    safe.append((key, value))
            elif tag == "img" and key in {"alt", "width", "height"}:
                if key == "alt" or re.fullmatch(r"[0-9]{1,4}", value):
                    safe.append((key, value))
            elif tag == "font" and key in {"color", "face", "size"} and re.fullmatch(r"[A-Za-z0-9 #,._-]+", value):
                safe.append((key, value))
            elif key == "align" and value in {"left", "right", "center", "justify"}:
                safe.append((key, value))
        if tag == "img" and not any(key == "src" for key, _ in safe):
            return
        attributes = "".join(f' {key}="{escape(value, quote=True)}"' for key, value in safe)
        self.output.append(f"<{tag}{attributes}>")

    def handle_endtag(self, tag):
        if self.blocked:
            if tag == self.blocked[-1]:
                self.blocked.pop()
            return
        if tag in TAGS and tag not in VOID:
            self.output.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.blocked:
            self.output.append(escape(data))


def clean_html(value, inline_images=False):
    parser = CleanHTML(inline_images)
    parser.feed(value)
    parser.close()
    return "".join(parser.output), parser.images
