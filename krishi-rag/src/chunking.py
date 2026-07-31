"""Section-aware chunking for OKF concepts.

We chunk on section boundaries rather than by fixed token windows. OKF bodies are
already structured by heading (spec §4.2 encourages structural markdown), so the
document hands us semantically coherent units for free — splitting a `# Dose`
table across two chunks would be actively harmful, since a retrieved half-dose is
worse than no dose.

Every chunk carries its parent concept's id, type, trust tier, and label_id so
the emitter can enforce grounding without a second lookup.
"""

from __future__ import annotations

from dataclasses import dataclass

from okf import Concept

# Sections that describe what a condition looks like. These carry the retrieval
# weight for image-derived queries, since they are written in the same register a
# vision model uses.
VISUAL_SECTIONS = {"visual symptoms"}

# Sections deliberately kept OUT of the retrieval index.
#
# "Distinguishing from similar conditions" necessarily describes the *other*
# disease's symptoms in order to contrast them. Indexed under its own file, that
# text matches queries about the other disease: a query about the rings that
# define early blight scored 0.616 against late blight's distinguishing section,
# because that section says "early blight lesions have concentric rings".
#
# The same applies to negations. Embedding models have no representation of
# "not", so writing "no rings, no circles" in the late blight file made it MORE
# similar to ring queries, not less. Contrastive and negative text is written for
# a human reader; it actively degrades vector retrieval.
#
# These sections stay in the bundle — they are valuable documentation and the
# right place to record confusable pairs — they are simply not embedded.
NON_RETRIEVAL_SECTIONS = {"distinguishing from similar conditions"}

# Sections that must never be split, because a partial read changes the meaning.
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
        """Text handed to the embedder.

        Title and heading are prepended so a chunk carries its own context — a
        bare dose table embedded alone is nearly meaningless in vector space.
        """
        parts = [self.concept_title]
        if self.heading:
            parts.append(self.heading)
        parts.append(self.text)
        return "\n".join(parts)


def _split_oversized(text: str, max_chars: int) -> list[str]:
    """Split on paragraph boundaries, never mid-table."""
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

    # A synthetic summary chunk. Carries title + description + tags so that a
    # query naming the condition directly matches without depending on any one
    # body section surviving retrieval.
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
        if heading_key in NON_RETRIEVAL_SECTIONS:
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
