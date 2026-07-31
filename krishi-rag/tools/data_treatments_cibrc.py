# -*- coding: utf-8 -*-
"""Treatment records read from CIB&RC "Major Uses of Pesticides" (31.03.2026).

Source: Central Insecticides Board & Registration Committee, DPPQS, Ministry of
Agriculture & Farmers Welfare.
  Insecticides: https://ppqs.gov.in/sites/default/files/updated_mup_insecticide_as_on_31.03.2026_c.pdf
  Fungicides:   https://ppqs.gov.in/sites/default/files/2._chemical_mup_fungicide_as_on_31.03.2026_0.pdf

THREE RULES THIS FILE FOLLOWS, because a wrong dose here poisons someone:

1. **One record per molecule PER CROP.** Mancozeb on potato and mancozeb on grape
   are separate registrations with different doses and different waiting periods.
   Crop registration is legally binding, so they never share a record.

2. **Where CIB&RC prints no waiting period, `phi_days` is null.** It is NOT filled
   with a guess, a related crop's figure, or a "safe default". The spoken answer
   says the waiting period is not stated and to read the container.

3. **Per-hectare figures are the registered ones. Per-acre is arithmetic**
   (/2.471) and marked derived. Toxicity triangle is NOT published by CIB&RC, so
   it is recorded as verify_on_container rather than asserted.

CIB&RC's own disclaimer applies: the compilation is "for guidance and not for
legal purposes" — the printed label on the container is the final authority.
"""

import io
import os

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
OUT = os.path.join(ROOT, "bundle", "treatments")

CIBRC_INSECT = "https://ppqs.gov.in/sites/default/files/updated_mup_insecticide_as_on_31.03.2026_c.pdf"
CIBRC_FUNGI = "https://ppqs.gov.in/sites/default/files/2._chemical_mup_fungicide_as_on_31.03.2026_0.pdf"

TPL = """---
type: Treatment
title: {title}
description: {desc}
tags: [{tags}]
source_type: pesticide_label
label_id: {label_id}
molecule: {molecule}
formulation: {formulation}
common_trade_names: [{trade}]
toxicity_triangle: verify_on_container
registered_crop: {crop}
registered_targets: [{targets}]
dose_per_hectare: {dose_ha}
dose_per_acre: {dose_acre}
dilution_per_litre: {dilution}
spray_volume_per_hectare: {water_ha}
spray_volume_per_acre: {water_acre}
phi_days: {phi}
verified: {{ by: process:cibrc-primary-source, at: 2026-07-31T00:00:00Z }}
sources:
  - id: cibrc-mup
    resource: {src}
    title: CIB&RC Major Uses of Pesticides, as on 31.03.2026
    author: process:cibrc-dppqs
    last_modified: 2026-03-31
generated: {{ by: process:research-agent, at: 2026-07-31T00:00:00Z }}
---

# Dose

| Field | Value |
|---|---|
| Per hectare | **{dose_ha}** (registered figure) |
| Per acre | **{dose_acre}** (derived, /2.471) |
| Water per hectare | {water_ha} |
| Mix rate | **{dilution}** |
| Waiting period before harvest | {phi_text} |

# Farmer-facing instruction

> {instruction}

# Safety

- Cover mouth, nose and hands. Spray with the wind at your back.
- Wash with soap and water immediately after spraying.
- Keep children and animals out of the field until the spray has dried.
- **Read the coloured triangle on the container before use.** CIB&RC does not
  publish the toxicity class in its registration table, so check the pack.

See [handling and protective measures](/safety/spray-safety.md).

# Constraints

{constraints}

# Applies to

{applies}
"""


def rec(**k):
    k.setdefault("trade", "")
    k.setdefault("constraints", "- Registered for **{}** only. Use on any other crop is off-label.".format(k["crop"]))
    phi = k.get("phi")
    if phi is None:
        k["phi"] = "null"
        k["phi_text"] = ("⚠ **Not stated by CIB&RC.** Read the container and ask "
                         "your Krishi Vigyan Kendra before harvesting.")
        k["instruction"] = (
            "Mix {dilution} in one litre of water. For one acre use {dose_acre} "
            "in about {water_acre} of water. The waiting period before harvest is "
            "not printed in the government table, so check the container and ask "
            "your Krishi Vigyan Kendra before you pick the crop.".format(**k)
        )
    else:
        k["phi_text"] = "**{} days**".format(phi)
        k["instruction"] = (
            "Mix {dilution} in one litre of water. For one acre use {dose_acre} "
            "in about {water_acre} of water. Do not harvest for {phi} days after "
            "spraying.".format(**k)
        )
    return k


R = [
    rec(f="mancozeb-75wp-potato", title="Mancozeb 75% WP for potato blight",
        desc="Multi-site protectant fungicide registered on potato for late blight and early blight.",
        tags="potato, blight, fungicide, mancozeb, protectant",
        label_id="CIBRC-MANC-75WP-POTATO", molecule="Mancozeb", formulation="75% WP",
        trade="Dithane M-45, Indofil M-45, Uthane M-45",
        crop="potato", targets="late blight, early blight",
        dose_ha="1.5 to 2.0 kg", dose_acre="600 to 800 g", dilution="2.0 to 2.7 g",
        water_ha="750 L", water_acre="300 L", phi=None, src=CIBRC_FUNGI,
        constraints="""- Registered for **potato** only. Use on any other crop is off-label.
- ⚠ **Source disagreement:** CIB&RC prints no waiting period for Mancozeb 75% **WP**
  on potato, but 3 to 5 days for the 75% **WG** form. Same molecule, same crop.
  Treat the longer figure as the safer one and confirm with a KVK.
- **Protectant only.** It forms a barrier on the leaf and stops spores establishing.
  Once lesions are visible a curative product is needed.
- Washed off by heavy rain. Reapply after significant rainfall.
- Keep away from alkaline materials, lime sulphur, Bordeaux mixture and copper.""",
        applies="- [Potato late blight](/diseases/potato-late-blight.md)\n- [Potato early blight](/diseases/potato-early-blight.md)"),

    rec(f="cymoxanil-mancozeb-potato", title="Cymoxanil 8% + Mancozeb 64% WP for potato late blight",
        desc="Curative plus protectant combination fungicide registered on potato for late blight.",
        tags="potato, late-blight, fungicide, curative",
        label_id="CIBRC-CYMO-MANC-POTATO", molecule="Cymoxanil + Mancozeb", formulation="8% + 64% WP",
        trade="Curzate M8, Moximate, Cursor",
        crop="potato", targets="late blight",
        dose_ha="1.5 kg", dose_acre="600 g", dilution="2 to 3 g",
        water_ha="500 to 750 L", water_acre="200 to 300 L", phi=10, src=CIBRC_FUNGI,
        constraints="""- Registered for **potato** only. Use on any other crop is off-label.
- Use when lesions are **already present**. Cymoxanil gives curative action a
  straight protectant cannot.
- ⚠ Cymoxanil is single-site. Resistance guidance is no more than 3 sprays a
  season, never two in a row, alternated with a straight multi-site.
- Keep away from alkaline materials and copper.""",
        applies="- [Potato late blight](/diseases/potato-late-blight.md)"),

    rec(f="difenoconazole-25ec-onion", title="Difenoconazole 25% EC for onion purple blotch",
        desc="Systemic triazole fungicide registered on onion for purple blotch.",
        tags="onion, purple-blotch, fungicide, triazole",
        label_id="CIBRC-DIFE-25EC-ONION", molecule="Difenoconazole", formulation="25% EC",
        trade="Score, Scoop",
        crop="onion", targets="purple blotch",
        dose_ha="500 ml", dose_acre="200 ml", dilution="1 ml (0.1 percent, label figure)",
        water_ha="500 L", water_acre="200 L", phi=20, src=CIBRC_FUNGI,
        applies="- [Onion purple blotch](/diseases/onion-purple-blotch.md)"),

    rec(f="difenoconazole-25ec-chilli", title="Difenoconazole 25% EC for chilli anthracnose",
        desc="Systemic triazole fungicide registered on chilli for die-back and fruit rot.",
        tags="chilli, anthracnose, dieback, fungicide",
        label_id="CIBRC-DIFE-25EC-CHILLI", molecule="Difenoconazole", formulation="25% EC",
        trade="Score, Scoop",
        crop="chilli", targets="die-back, fruit rot, anthracnose",
        dose_ha="250 to 500 ml", dose_acre="100 to 200 ml",
        dilution="0.5 ml (0.05 percent, label figure)",
        water_ha="500 to 1000 L", water_acre="200 to 400 L", phi=15, src=CIBRC_FUNGI,
        applies="- [Chilli anthracnose and die-back](/diseases/chilli-anthracnose.md)"),

    rec(f="fipronil-5sc-chilli", title="Fipronil 5% SC for chilli thrips",
        desc="Phenylpyrazole insecticide registered on chilli for thrips.",
        tags="chilli, thrips, insecticide",
        label_id="CIBRC-FIPR-5SC-CHILLI", molecule="Fipronil", formulation="5% SC",
        trade="Regent, Rebid",
        crop="chilli", targets="thrips",
        dose_ha="800 to 1000 ml", dose_acre="325 to 400 ml", dilution="1.6 to 2 ml",
        water_ha="500 L", water_acre="200 L", phi=7, src=CIBRC_INSECT,
        constraints="""- Registered for **chilli** only. ⚠ It is **not registered on onion** —
  a common off-label use that must be refused.
- Highly toxic to bees and to fish. Avoid flowering periods and keep washings away
  from ponds and canals.
- Direct the spray into the flowers and growing tips, where thrips shelter.""",
        applies="- [Chilli thrips](/diseases/chilli-thrips.md)\n- [Chilli black thrips](/diseases/chilli-black-thrips.md)"),

    rec(f="fenazaquin-10ec-chilli", title="Fenazaquin 10% EC for chilli yellow mite",
        desc="Quinazoline acaricide registered on chilli for yellow mite.",
        tags="chilli, mite, acaricide",
        label_id="CIBRC-FENA-10EC-CHILLI", molecule="Fenazaquin", formulation="10% EC",
        trade="Magister, Manthan",
        crop="chilli", targets="yellow mite",
        dose_ha="1250 ml", dose_acre="500 ml", dilution="2.1 to 3.1 ml",
        water_ha="400 to 600 L", water_acre="160 to 240 L", phi=10, src=CIBRC_INSECT,
        constraints="""- Registered for **chilli** only. Use on any other crop is off-label.
- Mites live on the **underside of the youngest leaves**. Direct the spray upward
  into the growing tips, not over the canopy.
- Toxic to fish. Keep washings away from water bodies.""",
        applies="- [Chilli yellow mite](/diseases/chilli-yellow-mite.md)"),

    rec(f="flubendiamide-okra", title="Flubendiamide 39.35% SC for okra fruit borer",
        desc="Diamide insecticide registered on okra for shoot and fruit borer.",
        tags="okra, borer, insecticide, diamide",
        label_id="CIBRC-FLUB-39SC-OKRA", molecule="Flubendiamide", formulation="39.35% SC",
        trade="Fame, Takumi",
        crop="okra", targets="shoot and fruit borer",
        dose_ha="100 to 125 ml", dose_acre="40 to 50 ml", dilution="0.2 to 0.25 ml",
        water_ha="500 L", water_acre="200 L", phi=3, src=CIBRC_INSECT,
        constraints="""- Registered for **okra** only. Use on any other crop is off-label.
- Low toxicity to bees, so it suits a flowering crop.
- **Clipping bored shoots and picking damaged pods removes more of the population
  than spraying does**, because the caterpillar feeds inside.""",
        applies="- [Okra shoot and fruit borer](/diseases/okra-shoot-fruit-borer.md)"),

    rec(f="imidacloprid-okra", title="Imidacloprid 17.8% SL for okra jassid",
        desc="Neonicotinoid insecticide registered on okra for jassid and leafhopper.",
        tags="okra, jassid, insecticide, neonicotinoid",
        label_id="CIBRC-IMID-17SL-OKRA", molecule="Imidacloprid", formulation="17.8% SL",
        trade="Confidor, Tatamida, Media",
        crop="okra", targets="jassid, leafhopper, whitefly, aphid",
        dose_ha="100 ml", dose_acre="40 ml", dilution="0.2 ml",
        water_ha="500 L", water_acre="200 L", phi=3, src=CIBRC_INSECT,
        constraints="""- Registered for **okra** only. Use on any other crop is off-label.
- ⚠ **Highly toxic to bees.** Avoid application when the crop is flowering.
- Jassids sit on the **leaf underside**. Direct the spray upward.""",
        applies="- [Okra jassid hopper burn](/diseases/okra-jassid.md)"),

    rec(f="emamectin-brinjal", title="Emamectin benzoate 5% SG for brinjal fruit borer",
        desc="Avermectin insecticide registered on brinjal for shoot and fruit borer.",
        tags="brinjal, borer, insecticide",
        label_id="CIBRC-EMAM-5SG-BRINJAL", molecule="Emamectin benzoate", formulation="5% SG",
        trade="Proclaim, Missile, EM-1",
        crop="brinjal", targets="shoot and fruit borer",
        dose_ha="200 g", dose_acre="81 g", dilution="0.4 g",
        water_ha="500 L", water_acre="200 L", phi=3, src=CIBRC_INSECT,
        constraints="""- Registered for **brinjal** only. Use on any other crop is off-label.
- ⚠ Highly toxic to bees. Toxic to fish.
- **Clip and destroy wilted shoots twice a week.** For this pest that removes more
  of the population than any spray, because the caterpillar feeds inside.""",
        applies="- [Brinjal shoot and fruit borer](/diseases/brinjal-shoot-fruit-borer.md)"),

    rec(f="imidacloprid-cotton", title="Imidacloprid 17.8% SL for cotton jassid",
        desc="Neonicotinoid insecticide registered on cotton for jassid and sucking pests.",
        tags="cotton, jassid, insecticide, neonicotinoid",
        label_id="CIBRC-IMID-17SL-COTTON", molecule="Imidacloprid", formulation="17.8% SL",
        trade="Confidor, Tatamida, Media",
        crop="cotton", targets="jassid, aphid, thrips, whitefly",
        dose_ha="100 to 125 ml", dose_acre="40 to 51 ml", dilution="0.2 ml",
        water_ha="500 to 700 L", water_acre="200 to 280 L", phi=40, src=CIBRC_INSECT,
        constraints="""- Registered for **cotton** only. Use on any other crop is off-label.
- ⚠ **Waiting period is 40 days** — the longest among the cotton products here.
- Highly toxic to bees.
- Rotate with an unrelated mode of action. Repeated neonicotinoid use drives
  resistance in whitefly and jassid.""",
        applies="- [Cotton jassid hopper burn](/diseases/cotton-jassid.md)"),

    rec(f="chlorantraniliprole-sugarcane", title="Chlorantraniliprole 18.5% SC for sugarcane shoot borer",
        desc="Diamide insecticide registered on sugarcane for early shoot borer.",
        tags="sugarcane, borer, insecticide, diamide",
        label_id="CIBRC-CHLO-18SC-SUGARCANE", molecule="Chlorantraniliprole",
        formulation="18.5% SC", trade="Coragen, Cover",
        crop="sugarcane", targets="early shoot borer",
        dose_ha="375 ml", dose_acre="152 ml", dilution="0.375 ml",
        water_ha="1000 L", water_acre="400 L", phi=208, src=CIBRC_INSECT,
        constraints="""- Registered for **sugarcane** only. Use on any other crop is off-label.
- ⚠ **Waiting period is 208 days.** That is normal for a long-duration crop, but it
  means this cannot be used late in the season.
- Low toxicity to bees.
- Apply early. The pest attacks in the first 60 days, and irrigation at the right
  interval reduces it substantially.""",
        applies="- [Sugarcane early shoot borer](/diseases/sugarcane-early-shoot-borer.md)"),

    rec(f="mancozeb-75wp-groundnut", title="Mancozeb 75% WP for groundnut leaf spot and rust",
        desc="Multi-site protectant fungicide registered on groundnut for tikka leaf spot and rust.",
        tags="groundnut, leaf-spot, rust, fungicide, tikka",
        label_id="CIBRC-MANC-75WP-GROUNDNUT", molecule="Mancozeb", formulation="75% WP",
        trade="Dithane M-45, Indofil M-45",
        crop="groundnut", targets="tikka leaf spot, rust",
        dose_ha="1.5 to 2.0 kg", dose_acre="600 to 800 g", dilution="2 to 2.7 g",
        water_ha="750 L", water_acre="300 L", phi=None, src=CIBRC_FUNGI,
        constraints="""- Registered for **groundnut** only. Use on any other crop is off-label.
- ⚠ CIB&RC prints no waiting period for this use. Confirm with a KVK before digging.
- **Protectant only.** Start before the disease establishes.
- Washed off by heavy rain. Reapply after significant rainfall.""",
        applies="- [Groundnut leaf spot and rust](/diseases/groundnut-late-leaf-spot.md)"),

    rec(f="thiamethoxam-mustard", title="Thiamethoxam 25% WG for mustard aphid",
        desc="Neonicotinoid insecticide registered on mustard for aphid.",
        tags="mustard, aphid, insecticide, neonicotinoid",
        label_id="CIBRC-THIA-25WG-MUSTARD", molecule="Thiamethoxam", formulation="25% WG",
        trade="Actara, Areva, Renova",
        crop="mustard", targets="aphid",
        dose_ha="50 to 100 g", dose_acre="20 to 40 g", dilution="0.05 to 0.2 g",
        water_ha="500 to 1000 L", water_acre="200 to 400 L", phi=21, src=CIBRC_INSECT,
        constraints="""- Registered for **mustard** only. Use on any other crop is off-label.
- ⚠ **Highly toxic to bees, and mustard is a heavily bee-visited flowering crop.**
  Apply outside flowering wherever possible, and in the late evening when bees are
  not foraging.
- Ladybird beetles and hoverfly larvae often control mustard aphid without any
  spray. Check for them before deciding.""",
        applies="- [Mustard aphid](/diseases/mustard-aphid.md)"),

    rec(f="thiamethoxam-mango", title="Thiamethoxam 25% WG for mango hopper",
        desc="Neonicotinoid insecticide registered on mango for hopper.",
        tags="mango, hopper, insecticide, neonicotinoid",
        label_id="CIBRC-THIA-25WG-MANGO", molecule="Thiamethoxam", formulation="25% WG",
        trade="Actara, Areva",
        crop="mango", targets="hopper",
        dose_ha="100 g", dose_acre="40 g", dilution="0.1 g",
        water_ha="1000 L", water_acre="400 L", phi=30, src=CIBRC_INSECT,
        constraints="""- Registered for **mango** only. Use on any other crop is off-label.
- ⚠ **Highly toxic to bees, and mango depends on insect pollination at flowering.**
  Time the spray to avoid open bloom.
- Opening the canopy by pruning reduces hopper pressure substantially.""",
        applies="- [Mango hopper](/diseases/mango-hopper.md)"),

    rec(f="copper-oxychloride-mango", title="Copper oxychloride 50% WG for mango anthracnose",
        desc="Copper protectant fungicide registered on mango for anthracnose.",
        tags="mango, anthracnose, fungicide, copper",
        label_id="CIBRC-COPP-50WG-MANGO", molecule="Copper oxychloride", formulation="50% WG",
        trade="Blitox, Fytolan, Blue Copper",
        crop="mango", targets="anthracnose",
        dose_ha="0.24 percent, that is 240 g in 100 L of water",
        dose_acre="as required to wet the canopy", dilution="2.4 g",
        water_ha="as required", water_acre="as required", phi=10, src=CIBRC_FUNGI,
        constraints="""- Registered for **mango** only. Use on any other crop is off-label.
- Dose is given as a **concentration**, not a fixed quantity per acre, because tree
  spraying is to wetting rather than to a fixed volume.
- Repeated copper accumulates in soil. Avoid unnecessary sprays.
- Keep away from acidic materials.""",
        applies="- [Mango anthracnose](/diseases/mango-anthracnose.md)"),

    rec(f="sulphur-80wp-mango", title="Sulphur 80% WP for mango powdery mildew",
        desc="Multi-site protectant fungicide registered on mango for powdery mildew.",
        tags="mango, powdery-mildew, fungicide, sulphur",
        label_id="CIBRC-SULP-80WP-MANGO", molecule="Sulphur", formulation="80% WP",
        trade="Sulfex, Thiovit, Cosavet",
        crop="mango", targets="powdery mildew",
        dose_ha="3.13 kg", dose_acre="1.27 kg", dilution="3 to 4 g",
        water_ha="750 to 1000 L", water_acre="300 to 400 L", phi=None, src=CIBRC_FUNGI,
        constraints="""- Registered for **mango** only. Use on any other crop is off-label.
- ⚠ CIB&RC prints no waiting period for this use. Confirm with a KVK.
- ⚠ **Do not apply in high heat.** Sulphur scorches foliage above roughly 32 °C.
  Spray in the cooler part of the day.
- Keep at least two weeks away from any oil spray. Sulphur plus oil burns foliage.""",
        applies="- [Mango powdery mildew](/diseases/mango-powdery-mildew.md)"),

    rec(f="mancozeb-75wp-grape", title="Mancozeb 75% WP for grape downy mildew",
        desc="Multi-site protectant fungicide registered on grape for downy mildew.",
        tags="grape, downy-mildew, fungicide, protectant",
        label_id="CIBRC-MANC-75WP-GRAPE", molecule="Mancozeb", formulation="75% WP",
        trade="Dithane M-45, Indofil M-45",
        crop="grape", targets="downy mildew",
        dose_ha="1.5 to 2.0 kg", dose_acre="600 to 800 g", dilution="2 to 2.7 g",
        water_ha="750 L", water_acre="300 L", phi=None, src=CIBRC_FUNGI,
        constraints="""- Registered for **grape** only. Use on any other crop is off-label.
- ⚠ CIB&RC prints no waiting period for this use. **Grape is eaten fresh and is a
  major export crop with strict residue limits** — confirm with a KVK before
  harvest, and keep the spray record.
- **Protectant only.** Apply before rain, not after symptoms appear.
- Washed off by heavy rain.""",
        applies="- [Grape downy mildew](/diseases/grape-downy-mildew.md)"),

    rec(f="sulphur-80wp-grape", title="Sulphur 80% WP for grape powdery mildew",
        desc="Multi-site protectant fungicide registered on grape for powdery mildew.",
        tags="grape, powdery-mildew, fungicide, sulphur",
        label_id="CIBRC-SULP-80WP-GRAPE", molecule="Sulphur", formulation="80% WP",
        trade="Sulfex, Thiovit, Cosavet",
        crop="grape", targets="powdery mildew",
        dose_ha="2.5 to 5.0 kg", dose_acre="1.0 to 2.0 kg", dilution="about 5 g",
        water_ha="750 to 1000 L", water_acre="300 to 400 L", phi=None, src=CIBRC_FUNGI,
        constraints="""- Registered for **grape** only. Use on any other crop is off-label.
- ⚠ CIB&RC prints no waiting period. Grape is eaten fresh with strict residue
  limits — confirm with a KVK before harvest.
- ⚠ **Do not apply above roughly 32 °C**; sulphur scorches vines in high heat.
- Keep at least two weeks away from any oil spray.""",
        applies="- [Grape powdery mildew](/diseases/grape-powdery-mildew.md)"),
]

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for k in R:
        fn = k.pop("f")
        io.open(os.path.join(OUT, fn + ".md"), "w", encoding="utf-8").write(TPL.format(**k))
        print("  wrote", fn + ".md")
    print(f"\n{len(R)} CIB&RC treatment records")
