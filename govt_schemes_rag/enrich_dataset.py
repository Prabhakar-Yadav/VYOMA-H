import json
import os
import sys

from config import COLLOQUIAL_TAGS, CATEGORY_TAGS


def enrich_dataset(input_file="schemes_dataset.jsonl", output_file="enriched_schemes_dataset.jsonl"):
    if not os.path.exists(input_file):
        print(f"Error: '{input_file}' not found in current directory!")
        print(f"Current directory: {os.getcwd()}")
        return

    enriched_count = 0
    total_count = 0

    with open(input_file, 'r', encoding='utf-8') as infile, \
         open(output_file, 'w', encoding='utf-8') as outfile:

        for line in infile:
            if not line.strip():
                continue
            total_count += 1
            scheme = json.loads(line.strip())

            # Build base searchable text from existing fields
            base_text = " ".join([
                scheme.get("scheme_name", ""),
                scheme.get("target_beneficiary", ""),
                scheme.get("benefit_details", ""),
                scheme.get("eligibility_criteria", ""),
                scheme.get("how_to_apply", ""),
                scheme.get("documents_required", ""),
                scheme.get("category", ""),
            ])

            # Inject scheme-specific colloquial tags
            scheme_id = scheme.get("scheme_id", "")
            injected_tags = list(COLLOQUIAL_TAGS.get(scheme_id, []))

            # Inject generic category-based tags
            category = scheme.get("category", "").lower()
            for cat_keyword, cat_tags in CATEGORY_TAGS.items():
                if cat_keyword in category:
                    injected_tags.extend(cat_tags)

            # Remove duplicates
            injected_tags = list(set(injected_tags))

            # Store enriched searchable text as a new field with Name Priming Boost
            scheme_name = scheme.get("scheme_name", "")
            name_boost = f"{scheme_name} {scheme_id} " * 3
            tags_string = " ".join(injected_tags)
            scheme["searchable_text"] = f"{name_boost} {base_text} {tags_string}".strip()

            if injected_tags:
                enriched_count += 1

            outfile.write(json.dumps(scheme, ensure_ascii=False) + "\n")

    print(f"Done! Processed {total_count} schemes.")
    print(f"Injected colloquial tags into {enriched_count} schemes.")
    print(f"Saved enriched dataset to: {output_file}")
    print(f"\nNext step: Update government_schemes_rag.py to load '{output_file}' instead of '{input_file}'")


if __name__ == "__main__":
    # Run from the same directory as schemes_dataset.jsonl
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    enrich_dataset()
