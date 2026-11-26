"""Document parsers producing page/section-aware text segments."""

from __future__ import annotations

import io
import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.errors import AppError


@dataclass
class Segment:
    text: str
    page: int | None = None
    section: str | None = None


@dataclass
class ParsedDocument:
    title: str | None
    segments: list[Segment]
    num_pages: int | None = None


class ParseError(AppError):
    code = "parse_error"
    status_code = 422


SUPPORTED_EXTENSIONS = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".txt": "txt",
    ".md": "md",
    ".markdown": "md",
}

_HEADING_MD = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def detect_source_type(filename: str) -> str:
    lower = filename.lower()
    for ext, kind in SUPPORTED_EXTENSIONS.items():
        if lower.endswith(ext):
            return kind
    raise ParseError(f"Unsupported file type: {filename}. Supported: PDF, DOCX, TXT, Markdown")


def parse_pdf(data: bytes) -> ParsedDocument:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        segments = []
        for i, page in enumerate(reader.pages, start=1):
            text = _clean(page.extract_text() or "")
            if text:
                segments.append(Segment(text=text, page=i))
        title = None
        if reader.metadata and reader.metadata.title:
            title = str(reader.metadata.title).strip() or None
    except (PdfReadError, ValueError, KeyError) as e:
        raise ParseError(f"Could not read PDF: {e}") from e
    if not segments:
        raise ParseError("PDF contains no extractable text (scanned PDFs need OCR)")
    return ParsedDocument(title=title, segments=segments, num_pages=len(reader.pages))


def parse_docx(data: bytes) -> ParsedDocument:
    import docx

    try:
        d = docx.Document(io.BytesIO(data))
    except Exception as e:
        raise ParseError(f"Could not read DOCX: {e}") from e
    segments: list[Segment] = []
    section: str | None = None
    buf: list[str] = []
    title = (d.core_properties.title or "").strip() or None

    def flush() -> None:
        if buf:
            segments.append(Segment(text="\n".join(buf), section=section))
            buf.clear()

    for p in d.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        style = (p.style.name or "").lower() if p.style is not None else ""
        if style.startswith("heading") or style == "title":
            flush()
            section = text
            title = title or text
        else:
            buf.append(text)
    flush()
    if not segments:
        raise ParseError("DOCX contains no text")
    return ParsedDocument(title=title, segments=segments)


def parse_markdown(text: str) -> ParsedDocument:
    segments: list[Segment] = []
    section: str | None = None
    title: str | None = None
    buf: list[str] = []
    in_code = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
        m = None if in_code else _HEADING_MD.match(line)
        if m:
            if "".join(buf).strip():
                segments.append(Segment(text=_clean("\n".join(buf)), section=section))
            buf = []
            section = m.group(2).strip()
            title = title or section
        else:
            buf.append(line)
    if "".join(buf).strip():
        segments.append(Segment(text=_clean("\n".join(buf)), section=section))
    if not segments:
        raise ParseError("Document is empty")
    return ParsedDocument(title=title, segments=segments)


def parse_text(text: str) -> ParsedDocument:
    text = _clean(text)
    if not text:
        raise ParseError("Document is empty")
    first = text.splitlines()[0].strip()
    return ParsedDocument(title=first[:120] if len(first) < 120 else None, segments=[Segment(text)])


def parse_html(html: str) -> ParsedDocument:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "form"]):
        tag.decompose()
    title = soup.title.string.strip() if soup.title and soup.title.string else None
    root = soup.find("main") or soup.find("article") or soup.body or soup
    segments: list[Segment] = []
    section: str | None = None
    buf: list[str] = []
    for el in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "pre", "td", "blockquote"]):
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        if el.name in {"h1", "h2", "h3", "h4"}:
            if buf:
                segments.append(Segment(text="\n".join(buf), section=section))
                buf = []
            section = text
            title = title or text
        else:
            buf.append(text)
    if buf:
        segments.append(Segment(text="\n".join(buf), section=section))
    if not segments:
        raise ParseError("No readable text found at URL")
    return ParsedDocument(title=title, segments=segments)


def parse_bytes(data: bytes, source_type: str) -> ParsedDocument:
    match source_type:
        case "pdf":
            return parse_pdf(data)
        case "docx":
            return parse_docx(data)
        case "md":
            return parse_markdown(_decode(data))
        case "txt":
            return parse_text(_decode(data))
        case "html":
            return parse_html(_decode(data))
    raise ParseError(f"Unsupported source type {source_type}")


def assert_public_url(url: str) -> None:
    """SSRF guard: only http(s) to public addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ParseError("Only http(s) URLs are supported")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as e:
        raise ParseError(f"Could not resolve host {parsed.hostname}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ParseError("URL resolves to a non-public address")


async def fetch_url(url: str, max_bytes: int) -> tuple[bytes, str]:
    assert_public_url(url)
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, max_redirects=5) as client:
        resp = await client.get(url, headers={"User-Agent": "DocuMind/1.0 (document ingestion)"})
        assert_public_url(str(resp.url))  # re-check after redirects
        if resp.status_code >= 400:
            raise ParseError(f"URL returned HTTP {resp.status_code}")
        if len(resp.content) > max_bytes:
            raise ParseError("Remote document too large")
        ctype = resp.headers.get("content-type", "").split(";")[0].strip()
        return resp.content, ctype


def source_type_for_content_type(ctype: str, url: str) -> str:
    if ctype == "application/pdf" or url.lower().endswith(".pdf"):
        return "pdf"
    if ctype in {"text/markdown"} or url.lower().endswith(".md"):
        return "md"
    if ctype == "text/plain":
        return "txt"
    return "html"


def _decode(data: bytes) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")  # pragma: no cover


def _clean(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
