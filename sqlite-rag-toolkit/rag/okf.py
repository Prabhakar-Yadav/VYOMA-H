"""OKF v0.2 bundle loader -- ported near-verbatim from
vyoma-hackathon-bhashini-plant-disease-rag/krishi-rag/src/okf.py (2026-08-11), which built
and evaluated this exact parser against the real corpus this file now also parses (153/153
tests passing there). Not reinvented here -- gramsahayak carries its own copy per this
project's "nothing here reaches outside this folder" convention (see README.md), same
reasoning agent/tools/pesticide_lookup.py already documents for its own dataset copy.

Parses a directory of markdown files with YAML frontmatter into Concept objects.
Spec: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md

Deliberately dependency-light: the whole point of OKF is that a bundle is readable
without bespoke tooling, and that property is worth preserving in the loader too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

RESERVED_FILENAMES = {"index.md", "log.md"}

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.MULTILINE)


@dataclass
class Section:
    """One `# Heading` block within a concept body."""

    heading: str
    level: int
    text: str


@dataclass
class Concept:
    """A single OKF concept document."""

    concept_id: str  # path within bundle, .md stripped
    path: Path
    frontmatter: dict
    body: str
    sections: list[Section] = field(default_factory=list)

    @property
    def type(self) -> str:
        return self.frontmatter.get("type", "Unknown")

    @property
    def title(self) -> str:
        return self.frontmatter.get("title") or self.path.stem.replace("-", " ").title()

    @property
    def description(self) -> str:
        return self.frontmatter.get("description", "")

    @property
    def tags(self) -> list[str]:
        return self.frontmatter.get("tags", []) or []

    @property
    def crop(self) -> str | None:
        return self.frontmatter.get("crop")

    @property
    def source_type(self) -> str:
        """Which body of knowledge this concept came from. Provenance + ranking-boost
        field only -- never a hard filter (see rag/retrieval.py)."""
        explicit = self.frontmatter.get("source_type")
        if explicit:
            return str(explicit)
        parts = self.concept_id.strip("/").split("/")
        return parts[0] if len(parts) > 1 else "general"

    @property
    def label_id(self) -> str | None:
        """Present only on Treatment concepts. The grounding key."""
        return self.frontmatter.get("label_id")

    @property
    def treatments(self) -> list[str]:
        return self.frontmatter.get("treatments", []) or []

    @property
    def trust_tier(self) -> str:
        verified = self.frontmatter.get("verified")
        if not verified:
            return "unverified"
        entries = verified if isinstance(verified, list) else [verified]
        for entry in entries:
            by = str(entry.get("by", "")) if isinstance(entry, dict) else str(entry)
            if by.startswith("human:"):
                return "human-reviewed"
        return "machine-confirmed"

    def section(self, heading: str) -> Section | None:
        target = heading.strip().lower()
        for sec in self.sections:
            if sec.heading.strip().lower() == target:
                return sec
        return None


def _split_sections(body: str) -> list[Section]:
    matches = list(_HEADING_RE.finditer(body))
    if not matches:
        stripped = body.strip()
        return [Section(heading="", level=0, text=stripped)] if stripped else []

    sections: list[Section] = []
    preamble = body[: matches[0].start()].strip()
    if preamble:
        sections.append(Section(heading="", level=0, text=preamble))

    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        text = body[match.end() : end].strip()
        if text:
            sections.append(
                Section(heading=match.group(2), level=len(match.group(1)), text=text)
            )
    return sections


def parse_concept(path: Path, bundle_root: Path) -> Concept | None:
    """Parse one markdown file. Returns None if it has no frontmatter."""
    raw = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        return None

    try:
        frontmatter = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML frontmatter in {path}: {exc}") from exc

    if not isinstance(frontmatter, dict):
        raise ValueError(f"Frontmatter in {path} is not a mapping")
    if "type" not in frontmatter:
        raise ValueError(f"Concept {path} is missing required field 'type'")

    body = match.group(2)
    concept_id = "/" + path.relative_to(bundle_root).as_posix()[: -len(".md")]

    return Concept(
        concept_id=concept_id,
        path=path,
        frontmatter=frontmatter,
        body=body,
        sections=_split_sections(body),
    )


def load_bundle(bundle_root: str | Path, include_indexes: bool = False) -> list[Concept]:
    """Load every concept document in a bundle. index.md/log.md are navigational, not
    knowledge-bearing, so excluded from retrieval by default."""
    root = Path(bundle_root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Bundle directory not found: {root}")

    concepts: list[Concept] = []
    for path in sorted(root.rglob("*.md")):
        if not include_indexes and path.name in RESERVED_FILENAMES:
            continue
        concept = parse_concept(path, root)
        if concept is not None:
            concepts.append(concept)

    if not concepts:
        raise ValueError(f"No concepts found in bundle: {root}")
    return concepts
