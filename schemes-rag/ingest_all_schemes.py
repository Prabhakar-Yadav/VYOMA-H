"""
Ingestion & Validation Engine for Government Schemes RAG Database.
Parses all Markdown database files in state_schemes/ and compiles them
into a validated schemes_dataset.jsonl. Supports both JSON line blocks and
structured Markdown sections.
"""
import glob
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ValidationError

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Scheme_Ingestor")


class SchemeRecord(BaseModel):
    scheme_id: str = Field(..., description="Unique scheme identifier code")
    scheme_name: str = Field(..., description="Canonical name of the scheme")
    category: str = Field(default="Agriculture", description="Primary operational category")
    target_beneficiary: str = Field(default="", description="Eligible target groups")
    benefit_details: str = Field(default="", description="Financial/input subsidy amounts")
    eligibility_criteria: str = Field(default="", description="Eligibility constraints")
    how_to_apply: str = Field(default="", description="Application workflow and portals")
    documents_required: str = Field(default="", description="Required verification documents")
    contact_details: str = Field(default="", description="Nodal authority and helpline")
    last_verified: str = Field(default="2026-08", description="Audit verification cycle")
    searchable_text: str = Field(default="", description="Dense keyword search representation")


def extract_json_lines_from_md(md_content: str) -> List[Dict[str, Any]]:
    """Extracts JSON lines embedded inside markdown files."""
    json_lines = []
    lines = md_content.splitlines()
    for line in lines:
        line_clean = line.strip()
        if line_clean.startswith("{") and line_clean.endswith("}") and '"scheme_id"' in line_clean:
            try:
                data = json.loads(line_clean)
                json_lines.append(data)
            except Exception as e:
                logger.warning(f"Failed to parse JSON line: {e} -> {line_clean[:60]}...")
    return json_lines


def extract_markdown_sections(md_content: str) -> List[Dict[str, Any]]:
    """Extracts schemes structured as markdown headers, e.g. ### [SCHEME_001] Name."""
    schemes = []
    # Match patterns like ### [SCHEME_001] Name or ### [UP_SCHEME_001] Name
    pattern = re.compile(r"###\s*\[([A-Za-z0-9_-]+)\]\s*([^\n]+)(.*?)(?=(?:###\s*\[|\Z))", re.DOTALL)
    matches = pattern.findall(md_content)

    for scheme_id, scheme_name, body in matches:
        scheme_id = scheme_id.strip()
        scheme_name = scheme_name.strip()

        # Extract field values using bullet point regex
        def get_field(field_name: str) -> str:
            m = re.search(rf"\*\s*\*\*Category:\*\*\s*([^\n]+)", body) if field_name == "category" else None
            if not m:
                m = re.search(rf"\*\s*\*\*{re.escape(field_name)}:\*\*\s*(.*?)(?=\n\*\s*\*\*|\Z)", body, re.DOTALL)
            if m:
                val = m.group(1).strip()
                return re.sub(r"\s+", " ", val)
            return ""

        category = get_field("Category") or "Agriculture"
        target_beneficiary = get_field("Target Beneficiary")
        benefit_details = get_field("Benefit Details")
        eligibility_criteria = get_field("Eligibility Criteria")
        how_to_apply = get_field("How to Apply")
        documents_required = get_field("Documents Required")
        contact_details = get_field("Contact Details") or get_field("Contact Details & Official Portals")

        schemes.append({
            "scheme_id": scheme_id,
            "scheme_name": scheme_name,
            "category": category,
            "target_beneficiary": target_beneficiary,
            "benefit_details": benefit_details,
            "eligibility_criteria": eligibility_criteria,
            "how_to_apply": how_to_apply,
            "documents_required": documents_required,
            "contact_details": contact_details,
            "last_verified": "2026-08",
        })
    return schemes


def build_searchable_text(data: Dict[str, Any]) -> str:
    """Builds a rich keyword search representation if missing."""
    parts = [
        data.get("scheme_name", ""),
        data.get("scheme_id", ""),
        data.get("category", ""),
        data.get("target_beneficiary", ""),
        data.get("benefit_details", ""),
        data.get("eligibility_criteria", ""),
        data.get("documents_required", ""),
    ]
    return " ".join([p for p in parts if p]).strip()


def ingest_all_schemes(source_dir: str, output_jsonl: str) -> int:
    """Parses all state/UT/central/carbon markdown files and outputs validated JSONL."""
    md_files = glob.glob(os.path.join(source_dir, "*.md"))
    logger.info(f"Discovered {len(md_files)} markdown scheme database files in {source_dir}")

    total_valid = 0
    all_schemes: Dict[str, SchemeRecord] = {}

    for md_path in md_files:
        filename = os.path.basename(md_path)
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Try JSON lines first
        extracted_lines = extract_json_lines_from_md(content)
        # If no JSON lines found, try parsing markdown sections
        if not extracted_lines:
            extracted_lines = extract_markdown_sections(content)

        file_valid = 0
        for item in extracted_lines:
            if not item.get("searchable_text"):
                item["searchable_text"] = build_searchable_text(item)

            try:
                validated = SchemeRecord(**item)
                all_schemes[validated.scheme_id] = validated
                file_valid += 1
            except ValidationError as ve:
                logger.warning(f"Validation error in {filename}: {ve}")

        logger.info(f"Parsed {file_valid} schemes from {filename}")

    os.makedirs(os.path.dirname(os.path.abspath(output_jsonl)), exist_ok=True)
    with open(output_jsonl, "w", encoding="utf-8") as out:
        for scheme_id, record in sorted(all_schemes.items()):
            out.write(json.dumps(record.model_dump(), ensure_ascii=False) + "\n")
            total_valid += 1

    logger.info(f"Successfully compiled {total_valid} validated schemes into {output_jsonl}")
    return total_valid


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    source_dir = os.path.join(base_dir, "state_schemes")
    output_jsonl = os.path.join(base_dir, "schemes_dataset.jsonl")
    ingest_all_schemes(source_dir, output_jsonl)
