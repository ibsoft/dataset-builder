"""UTF-8, editable structured sections, loss-conscious Markdown parsing and safe preview."""
import re
import unicodedata
import bleach
import markdown as markdown_lib

METADATA = [
    ("Knowledge Type", "Troubleshooting"),
    ("Category", "Connectivity"),
    ("Product", "TotalCare"),
    ("Device Models", ""),
    ("Operational Status", ""),
    ("Knowledge Status", "Draft"),
    ("Solution Status", "In Progress"),
    ("Language", "English"),
]
PROVENANCE = ("Created By", "Last Edited By", "Revision", "Created At", "Updated At")
MAX_SLUG_BYTES = 170

# Canonical values for the metadata fields that are selected from a fixed list
# rather than typed. The stored value is always the English canonical form, so
# the Markdown stays machine-readable for the RAG pipeline; the interface shows
# a translated label.
KNOWLEDGE_STATUS_VALUES = ('Draft', 'In Review', 'Approved', 'Published', 'Archived')
SOLUTION_STATUS_VALUES = ('Not Started', 'In Progress', 'Diagnostic Only', 'Verified', 'Rejected')
OPERATIONAL_STATUS_VALUES = ('Operational', 'Degraded', 'SPCommunicationDown', 'Offline', 'Maintenance')

# Metadata fields rendered as a combobox, mapped to their allowed values.
METADATA_CHOICES = {
    'Knowledge Status': KNOWLEDGE_STATUS_VALUES,
    'Solution Status': SOLUTION_STATUS_VALUES,
    'Operational Status': OPERATIONAL_STATUS_VALUES,
}


def normalize_choice(key, value, fallback=''):
    """Return the canonical value for a combobox metadata field.

    Unknown or empty values fall back to the field default so that the stored
    Markdown always contains one of the allowed values.
    """
    allowed = METADATA_CHOICES.get(key)
    if not allowed:
        return value
    if value in allowed:
        return value
    if fallback in allowed:
        return fallback
    return allowed[0]
DEFAULT_SECTIONS = [
    "PROBLEM DESCRIPTION", "POSSIBLE SYMPTOMS", "TOTALCARE MESSAGES", "POSSIBLE CAUSES",
    "DIAGNOSTIC PROCEDURE", "CORRECTIVE ACTIONS", "VERIFICATION",
    "REQUIRED INFORMATION FOR FURTHER DIAGNOSIS", "RELATED QUESTIONS",
]


def make_slug(title):
    """UTF-8-safe title slug that preserves Greek and other Unicode letters.

    Path separators are stripped so a title can never escape the KB directory;
    remaining punctuation collapses to ``_`` and the result is truncated on a
    character boundary to stay within filesystem filename limits.
    """
    normalized = unicodedata.normalize('NFC', title)
    cleaned = re.sub(r'[\\/]+', ' ', normalized)
    slug = re.sub(r'\W+', '_', cleaned, flags=re.UNICODE)
    slug = re.sub(r'_+', '_', slug).strip('_')
    encoded = slug.encode('utf-8')
    if len(encoded) > MAX_SLUG_BYTES:
        slug = encoded[:MAX_SLUG_BYTES].decode('utf-8', errors='ignore').rstrip('_')
    return slug or 'Untitled'


def validate_title(title):
    if not isinstance(title, str):
        raise ValueError("Title must be text")
    title = unicodedata.normalize("NFC", title.strip())
    if not 3 <= len(title) <= 240 or "\n" in title or "\r" in title:
        raise ValueError("Title must be 3–240 characters on one line")
    return title


def _line_kind(line, in_fence):
    """Only recognize headings outside fenced code blocks."""
    f = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
    if f:
        char, width = f.group(1)[0], len(f.group(1))
        if in_fence is None:
            return None, (char, width)
        if char == in_fence[0] and width >= in_fence[1] and not f.group(2).strip():
            return None, None
    if in_fence:
        return None, in_fence
    return re.match(r"^(#{1,3})[ \t]+(.+?)[ \t]*#*[ \t]*$", line), in_fence


def parse_markdown(raw):
    """Parse top-level metadata, ## sections, and ### Solution entries.

    Other ### headings stay intact in section bodies. Raw Markdown mode always
    remains available for documents whose structure exceeds this representation.
    """
    raw = raw.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    lines = raw.splitlines()
    top = []
    sections = []
    current = None
    fence = None
    for line in lines:
        h, fence = _line_kind(line, fence)
        if h and len(h.group(1)) == 2:
            current = {"title": h.group(2).strip(), "body_lines": []}
            sections.append(current)
        elif current is None:
            top.append(line)
        else:
            current["body_lines"].append(line)

    title = ""
    metadata = {}
    intro = []
    for line in top:
        h = re.match(r"^#\s+(.+?)\s*$", line)
        if h:
            title = re.sub(r"^TC-KB-\d+\s*:\s*", "", h.group(1), flags=re.I)
        else:
            m = re.match(r"^([A-Za-z][A-Za-z ]{1,50}):\s*(.*)$", line)
            if m:
                metadata[m.group(1)] = m.group(2).strip()
            else:
                intro.append(line)

    result_sections, solutions = [], []
    for sec in sections:
        body = "\n".join(sec["body_lines"]).strip("\n")
        if sec["title"].strip().upper() == "SOLUTIONS":
            current_solution = None
            in_fence = None
            for line in body.splitlines():
                h, in_fence = _line_kind(line, in_fence)
                if h and len(h.group(1)) == 3 and re.match(r"^Solution\s+\d+\s*:", h.group(2), re.I):
                    current_solution = {"title": re.sub(r"^Solution\s+\d+\s*:\s*", "", h.group(2), flags=re.I), "body_lines": []}
                    solutions.append(current_solution)
                elif current_solution is not None:
                    current_solution["body_lines"].append(line)
                else:
                    # Keep a non-standard SOLUTIONS section losslessly.
                    if not result_sections or result_sections[-1]["title"] != "SOLUTIONS":
                        result_sections.append({"title": "SOLUTIONS", "body": ""})
                    result_sections[-1]["body"] += line + "\n"
            for item in solutions:
                item["body"] = "\n".join(item.pop("body_lines")).strip("\n")
        else:
            result_sections.append({"title": sec["title"], "body": body})

    return {"title": title, "metadata": metadata, "intro": "\n".join(intro).strip("\n"),
            "sections": result_sections, "solutions": solutions}


def build_markdown(title, kb_id, metadata, intro, sections, solutions):
    chunks = [f"# {kb_id}: {title}", ""]
    ordered_keys = [key for key, _ in METADATA]
    for key in ordered_keys:
        chunks.append(f"{key}: {str(metadata.get(key, '')).strip()}")
    for key, value in metadata.items():
        if key not in ordered_keys and key not in PROVENANCE and re.match(r"^[A-Za-z][A-Za-z ]+$", key):
            chunks.append(f"{key}: {str(value).strip()}")
    chunks.append("")
    if intro and intro.strip():
        chunks.extend([intro.strip(), ""])
    for section in sections:
        name = str(section.get("title", "")).strip().replace("\n", " ")[:120]
        if not name:
            continue
        chunks += [f"## {name}", "", str(section.get("body", "")).strip("\n"), ""]
    if solutions:
        chunks.extend(["## SOLUTIONS", ""])
        for i, sol in enumerate(solutions, 1):
            name = str(sol.get("title", "")).strip().replace("\n", " ")[:120] or "Untitled solution"
            chunks += [f"### Solution {i}: {name}", "", str(sol.get("body", "")).strip("\n"), ""]
    return "\n".join(chunks).rstrip() + "\n"


def canonicalize_markdown(raw, title, kb_id, provenance):
    """Retain raw editing fidelity; enforce KB ID and server-owned audit fields."""
    if not isinstance(raw, str):
        raise ValueError("Markdown must be a UTF-8 string")
    if not isinstance(raw, str):
        raise ValueError("Markdown source must be text")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    if len(raw.encode("utf-8")) > 1_750_000:
        raise ValueError("Maximum Markdown document size is 1.75 MB")
    lines = raw.splitlines()
    if lines and re.match(r"^#\s+", lines[0]):
        lines[0] = f"# {kb_id}: {title}"
    else:
        lines = [f"# {kb_id}: {title}", ""] + lines
    # Provenance fields are never client-authoritative and are always regenerated.
    next_section = next((i for i, line in enumerate(lines) if re.match(r"^##\s+", line)), len(lines))
    header = [line for line in lines[:next_section] if not re.match(r"^(Created By|Last Edited By|Revision|Created At|Updated At):\s*", line)]
    lines = header + lines[next_section:]
    next_section = len(header)
    audit_lines = [f"{key}: {provenance[key]}" for key in PROVENANCE]
    lines[next_section:next_section] = audit_lines + [""]
    return "\n".join(lines).rstrip() + "\n"


_ALLOWED_TAGS = set(bleach.sanitizer.ALLOWED_TAGS).union({
    "h1", "h2", "h3", "h4", "h5", "h6", "p", "pre", "code", "br", "hr", "div",
    "span", "table", "thead", "tbody", "tr", "th", "td", "img", "del", "input",
    "sup", "sub", "blockquote", "ul", "ol", "li", "strong", "em",
})
_ALLOWED_ATTRS = {
    "a": ["href", "title"], "img": ["src", "alt", "title"],
    "th": ["align"], "td": ["align"], "code": ["class"],
    "input": ["type", "disabled", "checked"], "div": ["class"], "span": ["class"],
}


def render_preview(source):
    """Server-side HTML preview; sanitize raw HTML and malicious Markdown URLs."""
    if not isinstance(source, str) or len(source.encode("utf-8")) > 1_850_000:
        raise ValueError("Invalid or oversized Markdown")
    html = markdown_lib.markdown(source, extensions=["extra", "sane_lists", "nl2br", "toc"], output_format="html5")
    return bleach.clean(html, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS,
                        protocols=["http", "https", "mailto"], strip=True)
