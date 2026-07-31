# -*- coding: utf-8 -*-
"""Generate OKF disease concepts from researched crop data.

Kept as a script rather than hand-written files because the corpus is growing
past the point where hand-editing 40+ near-identical structures is reliable.
The generated .md files are the artefact; this is the source that produced them.

IMPORTANT: symptom text must be written POSITIVELY. Never "no rings", "unlike X",
"absent". Embedding models have no representation of negation, so a negative
sentence makes the concept MATCH the thing it is trying to exclude. Say what IS
present instead: "uniformly dark", "plain solid colour", "smooth surface".
"""

import io
import os

TPL = """---
type: {type}
title: {title}
description: {desc}
tags: [{tags}]
scientific_name: {sci}
crop: {crop}
local_names: [{local}]
severity_scale: [low, moderate, severe]
urgency: {urgency}
treatments: []
sources:
{sources}
generated: {{ by: human:prabhakar, at: 2026-07-31T00:00:00Z }}
---

# Visual symptoms

{symptoms}

# Distinguishing from similar conditions

{distinguish}

# When it matters

{matters}

# Treatment

**No verified treatment record has been added for this crop yet.** The device
names the condition and directs the farmer to their Krishi Vigyan Kendra rather
than quoting a dose it cannot verify.

# Non-chemical measures

{nonchem}
"""


def src(items):
    out = []
    for sid, url, title in items:
        out.append(
            "  - id: {}\n    resource: {}\n    title: {}\n"
            "    author: process:tnau-icar\n    last_modified: 2024-01-01".format(
                sid, url, title
            )
        )
    return "\n".join(out)


TNAU = ("tnau", "https://agritech.tnau.ac.in/crop_protection/crop_prot_crop_diseases.html",
        "TNAU Agritech Portal crop protection")
EAGRI = ("eagri", "http://eagri.org/eagri50/PATH371/lec08.pdf",
         "TNAU eagri PATH-371 and ENTO-331 course material")


def write_all(concepts, outdir):
    for d in concepts:
        d = dict(d)
        fn = d.pop("f")
        path = os.path.join(outdir, fn + ".md")
        io.open(path, "w", encoding="utf-8").write(TPL.format(**d))
        print("wrote", fn + ".md")
