"""Section-aware chunking for OKF concepts -- ported near-verbatim from
vyoma-hackathon-bhashini-plant-disease-rag/krishi-rag/src/chunking.py (2026-08-11).

Kept as-is deliberately, not redesigned: this exact design (chunk on heading
boundaries, exclude contrastive/negative sections from the index, never split atomic
sections like dose tables) is a real, evaluated result (153/153 tests, see that
repo's README "Lessons that changed the design" Β§2), not a hypothesis. See
gramsahayak/G1-G2-VECTORDB-PLAN.md (copied alongside this build) for why this was kept
rather than re-derived.
"""

from __future__ import annotations

from dataclasses import dataclass

from rag.okf import Concept

VISUAL_SECTIONS = {"visual symptoms"}

NON_RETRIEVAL_SECTIONS = {"distinguishing from similar conditions"}
NON_RETRIEVAL_PREFIXES = ("distinguishing from", "telling it apart", "not to be confused")

ATOMIC_SECTIONS = {"dose", "farmer-facing instruction", "safety", "constraints"}

MAX_CHARS = 1200


@dataclass
class Chunk:
    chunk_id: str
    concept_id: str
    concept_title: str
    concept_type: str
    heading: str
    text: str
    trust_tier: str
    source_type: str = "general"
    crop: str | None = None
    label_id: str | None = None
    is_visual: bool = False

    @property
    def embed_text(self) -> str:
        parts = [self.concept_title]
        if self.heading:
            parts.append(self.heading)
        parts.append(self.text)
        return "\n".join(parts)


def _split_oversized(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    parts: list[str] = []
    current: list[str] = []
    size = 0
    for para in text.split("\n\n"):
        if size + len(para) > max_chars and current:
            parts.append("\n\n".join(current))
            current, size = [], 0
        current.append(para)
        size += len(para) + 2
    if current:
        parts.append("\n\n".join(current))
    return parts


def chunk_concept(concept: Concept) -> list[Chunk]:
    chunks: list[Chunk] = []

    summary_bits = [concept.title]
    if concept.description:
        summary_bits.append(concept.description)
    if concept.tags:
        summary_bits.append("Tags: " + ", ".join(concept.tags))
    local_names = concept.frontmatter.get("local_names") or []
    if local_names:
        summary_bits.append("Also called: " + ", ".join(str(n) for n in local_names))
    sci = concept.frontmatter.get("scientific_name")
    if sci:
        summary_bits.append(f"Scientific name: {sci}")

    chunks.append(
        Chunk(
            chunk_id=f"{concept.concept_id}#summary",
            concept_id=concept.concept_id,
            concept_title=concept.title,
            concept_type=concept.type,
            heading="Summary",
            text="\n".join(summary_bits),
            trust_tier=concept.trust_tier,
            source_type=concept.source_type,
            crop=concept.crop,
            label_id=concept.label_id,
        )
    )

    for sec in concept.sections:
        heading_key = sec.heading.strip().lower()
        if heading_key in NON_RETRIEVAL_SECTIONS or heading_key.startswith(
                NON_RETRIEVAL_PREFIXES):
            continue
        pieces = (
            [sec.text]
            if heading_key in ATOMIC_SECTIONS
            else _split_oversized(sec.text, MAX_CHARS)
        )
        for i, piece in enumerate(pieces):
            suffix = f"#{heading_key.replace(' ', '-') or 'body'}"
            if len(pieces) > 1:
                suffix += f"-{i}"
            chunks.append(
                Chunk(
                    chunk_id=f"{concept.concept_id}{suffix}",
                    concept_id=concept.concept_id,
                    concept_title=concept.title,
                    concept_type=concept.type,
                    heading=sec.heading,
                    text=piece,
                    trust_tier=concept.trust_tier,
                    source_type=concept.source_type,
                    crop=concept.crop,
                    label_id=concept.label_id,
                    is_visual=heading_key in VISUAL_SECTIONS,
                )
            )

    return chunks


def chunk_bundle(concepts: list[Concept]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for concept in concepts:
        chunks.extend(chunk_concept(concept))
    return chunks
