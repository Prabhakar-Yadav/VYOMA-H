# -*- coding: utf-8 -*-
"""Convert the researched government-schemes markdown into OKF concepts.

The research file is already well-structured — one `##` section per scheme or
practice topic — so this splits on those boundaries rather than rewriting the
content by hand. Sources are lifted out of the trailing "Sources:" line into
frontmatter, and any line carrying a warning marker is promoted to a freshness
flag, because scheme rules go stale between budgets.
"""

import io
import os
import re

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SRC = os.path.join(ROOT, "research", "govt-guidelines.md")
OUT = os.path.join(ROOT, "bundle", "guidelines")

TPL = """---
type: {type}
title: {title}
description: {desc}
tags: [{tags}]
source_type: govt_guideline
{extra}sources:
{sources}
generated: {{ by: process:research-agent, at: 2026-07-31T00:00:00Z }}
---

{body}
"""


def slug(text):
    s = re.sub(r"[^\w\s-]", "", text.lower())
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return re.sub(r"-+", "-", s)[:60]


def main():
    os.makedirs(OUT, exist_ok=True)
    text = io.open(SRC, encoding="utf-8").read()

    # Part 2 begins the practice-guidance topics.
    split_at = text.find("# PART 2")
    part1, part2 = text[:split_at], text[split_at:] if split_at > 0 else ""

    written = 0
    for part, ctype, base_tags in (
        (part1, "Scheme", "scheme, government, subsidy"),
        (part2, "Practice Guidance", "guidance, official, practice"),
    ):
        # Split on top-level "## N. Title" headings only.
        sections = re.split(r"\n## (?=\d+\.)", part)
        for sec in sections[1:]:
            lines = sec.split("\n")
            heading = lines[0].strip()
            body = "\n".join(lines[1:]).strip()

            # Drop the horizontal rule the research file uses between sections.
            body = re.sub(r"\n-{3,}\s*$", "", body).strip()

            # Pull the trailing Sources line into frontmatter.
            src_urls = []
            m = re.search(r"^Sources?:\s*(.+)$", body, re.M)
            if m:
                src_urls = [u.strip() for u in m.group(1).split("|") if u.strip()]
                body = body[: m.start()].rstrip()

            # Title without the leading number.
            title = re.sub(r"^\d+\.\s*", "", heading).strip()
            short = title.split("—")[0].strip()

            stale = "⚠" in body or "⚠" in heading
            extra = "freshness: verify_before_use\n" if stale else ""

            first_para = ""
            for para in body.split("\n\n"):
                cleaned = re.sub(r"[*#>-]", "", para).strip()
                if len(cleaned) > 40:
                    first_para = " ".join(cleaned.split())[:180]
                    break

            if not src_urls:
                src_urls = ["https://www.myscheme.gov.in"]
            sources = "\n".join(
                "  - id: src-{}\n    resource: {}\n    author: process:govt-india\n"
                "    last_modified: 2026-07-31".format(i, u)
                for i, u in enumerate(src_urls[:4])
            )

            fn = slug(short) + ".md"
            io.open(os.path.join(OUT, fn), "w", encoding="utf-8").write(
                TPL.format(
                    type=ctype,
                    title=title.replace(":", " -"),
                    desc=(first_para or title).replace(":", " -"),
                    tags=base_tags,
                    extra=extra,
                    sources=sources,
                    body=body,
                )
            )
            written += 1
            print("  wrote", fn)

    print(f"\n{written} guideline concepts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
