# -*- coding: utf-8 -*-
"""Grape and chilli powdery mildew.

Both were in the research but missed in the first generation pass — the 93-case
suite caught the gap by returning the nearest wrong disease on the same crop
(grape downy mildew for a grape powdery mildew query).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_concepts import src, write_all

TNAU_M = ("tnau-mildew", "https://agritech.tnau.ac.in/crop_protection/crop_prot_crop_diseases.html",
          "TNAU Agritech Portal crop protection")
EAGRI_M = ("eagri-mildew", "http://eagri.org/eagri50/PATH371/lec04.pdf",
           "TNAU eagri PATH-371 fruit and vegetable diseases")

CONCEPTS = [
    dict(
        f="grape-powdery-mildew", type="Disease", title="Grape powdery mildew",
        desc="Fungal disease dusting grape leaves and berries with dry grey-white powder and splitting the berry skin open.",
        tags="grape, powdery-mildew, fungal", sci="Uncinula necator", crop="grape",
        local="चूर्णिल आसिता, churnil asita, भभूतिया रोग, bhuri", urgency="high",
        sources=src([EAGRI_M, TNAU_M]),
        symptoms="""- **Dull greyish-white powdery or dusty coating, mostly on the UPPER leaf surface**, looking like ash or flour sprinkled over the leaf.
- The powder **rubs off with a finger**, leaving a brown-purple stain on the leaf beneath.
- Affected leaves **curl upward at the edges, distort, and lose their fresh green colour**, turning a dull greyish-green.
- Canes and shoots develop **dark brown to black irregular blotches** where the powder sat.
- Flowers on infected clusters **dry and shed**, leaving loose bunches with big gaps and few berries.
- Small green berries carry a **grey-white dusty film** and drop off.
- Larger berries carry powder on the skin and then **crack and split open**, often in a star-shaped or lengthwise split, exposing the pulp and seeds.
- Split berries become entry points for secondary rots, and the bunch dries with a dusty grey look.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Grape downy mildew | Powdery mildew is **dry grey-white powder on the UPPER surface, and the berries crack and split open**. Downy mildew is white fluffy growth on the LOWER surface beneath a translucent oil spot, and the berry skin stays smooth and intact. |
| Road dust on the leaf | The mildew **regrows within days after being wiped off** and leaves a brown-purple stain underneath. Dust rinses off with plain water and the leaf stays green. |""",
        matters="Splits the berries and makes the bunch unsellable within a season. The fungus overwinters as dormant mycelium inside buds and canes, so it carries over unless pruned material is destroyed.",
        nonchem="""- **Prune out and burn infected shoots and canes at pruning**; the fungus survives as dormant mycelium in buds and shoots.
- Thin the canopy and remove basal leaves for sunlight and airflow.
- Avoid dense sultry shade and excessive vegetative growth from over-fertilising."""),

    dict(
        f="chilli-powdery-mildew", type="Disease", title="Chilli powdery mildew",
        desc="Fungal disease growing white powder on the underside of chilli leaves with yellow blotches showing on top, causing heavy leaf fall.",
        tags="chilli, powdery-mildew, fungal", sci="Leveillula taurica", crop="chilli",
        local="चूर्णिल आसिता, भभूतिया रोग, bhabhutiya rog", urgency="moderate",
        sources=src([EAGRI_M, TNAU_M]),
        symptoms="""- **White to greyish powdery patches sit on the LOWER leaf surface** — this location is the key for this species.
- The matching spot on the **upper surface shows a pale light-green to bright yellow blotch**, often angular and bounded by the veins.
- The powder **rubs off easily onto a finger or cloth**, leaving a dulled green patch underneath.
- Small separate white tufts appear first, then merge into large felted mats across the underside.
- Yellow upper-surface patches later brown off in the centre and the leaf turns papery.
- **Heavy leaf drop starting from the older lower leaves upward**, leaving bare stems with fruit hanging exposed.
- Fallen leaves lie on the ground still bearing white powder on the underside.
- Fruit on defoliated plants shows sunken bleached white patches from sun exposure.""",
        distinguish="""| Looks like | Tell it apart by |
|---|---|
| Spray residue or dust | The mildew growth is **dry, white and rubs off cleanly, and it pairs a yellow patch on top with white powder directly beneath**. |
| Chilli thrips damage | Thrips give a silvery bronzed sheen on the upper surface with tiny black excreta dots and upward leaf cupping. |""",
        matters="Causes 14 to 30 percent loss through defoliation, and the bare plants then expose fruit to sunscald. Easy to miss entirely, because the growth is on the leaf underside — a farmer checking leaf tops sees only yellow patches.",
        nonchem="""- **Inspect leaf undersides weekly**; the disease is invisible if only the top of the leaf is checked.
- Remove and destroy the lowest infected leaves early to slow the upward spread.
- Widen spacing and orient rows for airflow; crowded canopies hold the humidity this fungus needs.
- Clear and destroy crop debris after harvest, where dormant mycelium survives.
- Avoid heavy nitrogen pushes that produce soft dense foliage."""),
]

if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bundle", "diseases")
    write_all(CONCEPTS, os.path.normpath(out))
