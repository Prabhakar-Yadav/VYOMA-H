# -*- coding: utf-8 -*-
"""Convert researched entomology and pathology markdown into OKF concepts.

These two corpora answer *why* and *when*, which symptom identification alone
cannot. Entomology carries life cycles, seasonal peaks, alternate hosts and
natural enemies. Pathology carries the organism type — and the single most
valuable fact in the whole bundle is that fungicides act on fungi, so a farmer
buying one for a bacterial or viral disease loses both the money and the crop.

Both files are already sectioned by `##`, so this splits on those boundaries
rather than rewriting content. Source URLs in the body are lifted into
frontmatter; the body keeps its own inline citations.
"""

import io
import os
import re

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

JOBS = [
    ("entomology.md", "entomology", "Insect", "entomology, insect, biology, life-cycle"),
    ("pathology.md", "pathology", "Pathogen", "pathology, disease, biology, pathogen"),
]

TPL = """---
type: {type}
title: {title}
description: {desc}
tags: [{tags}]
source_type: {stype}
{sci}sources:
{sources}
generated: {{ by: process:research-agent, at: 2026-08-01T00:00:00Z }}
---

{body}
"""


def slug(text):
    s = re.sub(r"[^\w\s-]", "", text.lower())
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return re.sub(r"-+", "-", s)[:58]


def clean_title(raw):
    t = re.sub(r"^[A-Z]?\d+\.\s*", "", raw).strip()
    t = re.sub(r"\*+", "", t)
    t = re.sub(r"\s*\((?:Hemiptera|Lepidoptera|Thysanoptera|Acari|Diptera|Coleoptera)[^)]*\)", "", t)
    return t.replace(":", " -").strip()


def main():
    total = 0
    for fname, folder, ctype, tags in JOBS:
        src_path = os.path.join(ROOT, "research", fname)
        if not os.path.exists(src_path):
            print(f"  skip {fname} (not found)")
            continue
        out_dir = os.path.join(ROOT, "bundle", folder)
        os.makedirs(out_dir, exist_ok=True)
        text = io.open(src_path, encoding="utf-8").read()

        for sec in re.split(r"\n## (?=[A-Z]?\d)", text)[1:]:
            lines = sec.split("\n")
            heading = lines[0].strip()
            body = "\n".join(lines[1:]).strip()
            body = re.sub(r"\n-{3,}\s*$", "", body).strip()
            if len(body) < 200:
                continue

            title = clean_title(heading)
            urls = re.findall(r"https?://[^\s)\]|>]+", body)
            seen, uniq = set(), []
            for u in urls:
                u = u.rstrip(".,;")
                if u not in seen:
                    seen.add(u)
                    uniq.append(u)
            if not uniq:
                uniq = ["https://agritech.tnau.ac.in"]
            sources = "\n".join(
                "  - id: src-{}\n    resource: {}\n    author: process:tnau-icar\n"
                "    last_modified: 2026-08-01".format(i, u)
                for i, u in enumerate(uniq[:4])
            )

            m = re.search(r"\*([A-Z][a-z]+ [a-z]+)\*", heading)
            sci = f"scientific_name: {m.group(1)}\n" if m else ""

            desc = ""
            for para in body.split("\n\n"):
                c = re.sub(r"[*#>|`\[\]]", "", para)
                c = re.sub(r"https?://\S+", "", c).strip()
                if len(c) > 50 and not c.startswith("|"):
                    desc = " ".join(c.split())[:170]
                    break
            desc = (desc or title).replace(":", " -")

            fn = slug(title) + ".md"
            io.open(os.path.join(out_dir, fn), "w", encoding="utf-8").write(
                TPL.format(type=ctype, title=title, desc=desc, tags=tags,
                           stype=folder, sci=sci, sources=sources, body=body)
            )
            total += 1
        print(f"  {folder}: done")
    print(f"\n{total} biology concepts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
