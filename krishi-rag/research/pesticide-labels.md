# CIB&RC-Registered Pesticide Label Data — Indian Crops

**Purpose:** authoritative chemical-control reference for a farmer advisory device.
**Compiled:** 2026-07-31
**Status:** COMPLETE for the requested crop list. 33 crop+problem combinations covered.
**Registration data current as on 31/03/2026** (CIB&RC Major Uses of Pesticides).
**Re-check against a newer CIB&RC edition before shipping** — registrations are added and
withdrawn continuously, and a withdrawn registration makes a stored dose illegal to give.

---

## 0. PRIMARY SOURCE AND HOW TO READ THIS FILE

### Primary source (THE authority)

Central Insecticides Board & Registration Committee (CIB&RC), Directorate of Plant
Protection, Quarantine & Storage (DPPQS), Ministry of Agriculture & Farmers Welfare.
**"Major Uses of Pesticides (Registered under the Insecticides Act, 1968)" — UPTO 31/03/2026.**

- Index page: https://ppqs.gov.in/divisions/cib-rc/major-uses-of-pesticides
- **Insecticides (as on 31.03.2026):** https://ppqs.gov.in/sites/default/files/updated_mup_insecticide_as_on_31.03.2026_c.pdf
- **Fungicides (as on 31.03.2026):** https://ppqs.gov.in/sites/default/files/2._chemical_mup_fungicide_as_on_31.03.2026_0.pdf
- Bio-fungicides: https://ppqs.gov.in/sites/default/files/3._bio_pesticide_mup_biofungicide_as_on_31.03.2026.pdf
- Bio-insecticides: https://ppqs.gov.in/sites/default/files/6._mup_bio_insecticide_31.03.2026.pdf

Every dose in this file that is marked **[CIB&RC]** was read directly out of the table
cells of one of those two PDFs (page number given). CIB&RC's own disclaimer applies:
*"compiled on the basis of available information for guidance and not for legal purposes"* —
**the printed label on the container is the final legal authority.**

### The CIB&RC table columns mean

| Column | Meaning |
|---|---|
| Crop | The **only** crop the use is registered on |
| Common name of the pest/disease | The **only** target registered |
| a.i. (g) | grams of **active ingredient** per hectare |
| Formulation (g/ml) | grams or ml of **product as sold** per hectare — *this is the number a farmer measures* |
| Dilution in water (L) | **spray volume** of water per hectare |
| Waiting period | **pre-harvest interval (PHI)** in days from last application to harvest |

### Unit conventions used here

- **Per hectare = the registered figure.** Quoted verbatim.
- **Per acre = arithmetic conversion only** (÷ 2.471). It is *derived*, not separately
  registered. Marked `(derived)` everywhere. Rounded to farmer-usable numbers.
- **Dilution per litre** = formulation dose ÷ spray volume, i.e. the in-tank concentration.
  Derived unless CIB&RC itself gives a %/per-litre figure (some entries do).
- 1 ha = 2.471 acre. 1 acre = 0.4047 ha.

### Fields CIB&RC does NOT publish — read this before trusting them

The MUP tables contain **only** crop, target, a.i. dose, formulation dose, spray volume
and PHI. They do **not** contain trade names, toxicity triangle colour, re-entry interval,
maximum applications per season, or tank-mix compatibility. Therefore:

- **Trade names** — given as "commonly marketed in India as…" for farmer recognition only.
  Not from CIB&RC. Brands change, and the *same brand name can carry a different
  formulation strength*. ⚠ Always verify the % and formulation type on the pack, not the brand.
- **Toxicity triangle colour** — set by Insecticides Rules 1971, Rule 19 / First Schedule,
  on the basis of oral & dermal LD50 **of the finished formulation**, so it varies between
  formulations and even between manufacturers of the same molecule. Colours below are the
  class usually printed for that formulation and are marked ⚠ — **read the triangle on the pack**.
  Bands: Red = extremely/highly toxic; Yellow = moderately toxic; Blue = slightly toxic;
  Green = comparatively free from danger.
- **Re-entry interval (REI)** — India does **not** stipulate REI on pesticide labels;
  CIB&RC prescribes only the waiting period. Where a number appears below it comes from an
  IPM/extension package, not the label. Default safe practice: keep people and livestock out
  until the spray has dried, and a minimum of 24 h for red/yellow-triangle products.
- **Maximum applications per season** — not part of Indian registration for most products.
  Where stated below it is from a NIPHM/SAU package, not the label. Mostly "NOT FOUND".
- **Incompatibility** — general chemistry cautions, flagged as advisory not label text.

### Universal tank-mix rules (apply to every product in this file)

1. **Never mix any product with Bordeaux mixture, lime sulphur, or other strongly alkaline
   materials.** Most organophosphates, carbamates, synthetic pyrethroids and the
   sulfonylurea/strobilurin chemistries hydrolyse rapidly above pH 8.
2. **Captan, captafol, folpet and dodine must not be mixed with, or applied within
   10–14 days of, oil sprays or highly alkaline materials** — severe phytotoxicity.
3. **Do not mix EC formulations with WP/WG in hard or alkaline water** without a jar test.
4. **Copper fungicides + acidic/organophosphate products** → free copper release → burn.
   Keep a 7-day gap.
5. **Do not tank-mix two products from the same IRAC/FRAC mode-of-action group** — it
   accelerates resistance without adding control.
6. Always do a **jar test** (small container, same water, same proportions, wait 15 min)
   before any mixture not printed on a label.
7. **Rotate FRAC/IRAC groups.** No single-site fungicide (strobilurin QoI-11,
   SDHI-7, triazole-3) more than 2–3 sprays per season, never consecutively.

### Meaning of the flags used below

- **[CIB&RC]** — dose read from the official Major Uses of Pesticides table. Trustworthy.
- **NOT FOUND — requires verification** — no authoritative Indian dose located. Do not guess.
- **NOT REGISTERED** — the product is used on this crop in practice but is **not** on the
  CIB&RC label for it. Illegal to recommend; residues are unregulated; MRLs do not exist.
- ⚠ — uncertainty, source disagreement, or a field CIB&RC does not publish.

---

---

# HIGH PRIORITY CROPS

## 1. POTATO

Source for every dose in this section unless stated:
CIB&RC MUP Fungicides 31.03.2026 — https://ppqs.gov.in/sites/default/files/2._chemical_mup_fungicide_as_on_31.03.2026_0.pdf

### 1.1 Potato — LATE BLIGHT (*Phytophthora infestans*)

**Strategy note:** late blight moves faster than any spray schedule. Contact/multi-site
(mancozeb, chlorothalonil, copper) go on **before** the epidemic; systemics
(cymoxanil, dimethomorph, mandipropamid, cyazofamid, metalaxyl) are for when infection
has started, and must always be applied **with or as a pre-mix containing a multi-site
partner**, never alone — metalaxyl resistance in Indian *P. infestans* is widespread.

| # | Product | Dose/ha (formulation) | Dose/acre (derived) | Water/ha | Dilution | PHI |
|---|---|---|---|---|---|---|
| 1 | **Mancozeb 75% WP** | 1.5–2.0 kg | 600–800 g | 750 L | 2.0–2.7 g/L | ⚠ "-" not stated |
| 2 | **Mancozeb 75% WG** | 1.0 kg | 400 g | 500 L | 2 g/L | 3–5 d |
| 3 | **Cymoxanil 8% + Mancozeb 64% WP** | 1.5 kg | 600 g | 500–750 L | 2–3 g/L | 10 d |
| 4 | **Metalaxyl-M 4% + Mancozeb 64% WP** | 2.5 kg (0.25%) | 1.0 kg | 500–1000 L | 2.5 g/L | 24 d |
| 5 | **Dimethomorph 50% WP** | 1.0 kg | 400 g | 750 L | 1.33 g/L | 16 d |
| 6 | **Cyazofamid 34.5% SC** | 200 ml | 80 ml | 500 L | 0.4 ml/L | 27 d |
| 7 | **Mandipropamid 23.4% SC** | 400–600 ml | 160–240 ml | 500–750 L | **0.8 ml/L (label figure)** | 40 d |
| 8 | **Fenamidone 10% + Mancozeb 50% WG** | 1.25–1.5 kg | 500–600 g | 500 L | 2.5–3 g/L | 30 d |
| 9 | **Famoxadone 16.6% + Cymoxanil 22.1% SC** | 500 ml | 200 ml | 500 L | 1 ml/L | 40 d |
| 10 | **Copper oxychloride 50% WP** | 2.5 kg | 1.0 kg | 750–1000 L | 2.5–3.3 g/L | ⚠ "-" not stated |
| 11 | **Metiram 70% WG** | 2.0 kg | 810 g | 500–750 L | 2.7–4 g/L | 17 d |
| 12 | **Amisulbrom 20% SC** | 500 ml | 200 ml | 375–500 L | 1.0–1.3 ml/L | 19 d |
| 13 | **Azoxystrobin 23% SC** | 500 ml | 200 ml | 500 L | 1 ml/L | 12 d |

**Product detail — the two a farmer will most often use:**

**Mancozeb 75% WP** (dithiocarbamate, FRAC M03 multi-site)
- ⚠ Trade names (not CIB&RC): Dithane M-45, Indofil M-45, Uthane M-45, Manzate, Emthane M-45.
- Registered crop/target: Potato — Late blight **and** Early blight (single MUP row).
- **Registered dose: 1.5–2.0 kg formulation/ha (= 1.125–1.5 kg a.i./ha).** Per acre 600–800 g (derived).
- Spray volume: **750 L/ha** = ~300 L/acre. Dilution ≈ 2.0–2.7 g per litre.
- ⚠ **Source disagreement on PHI:** CIB&RC prints "-" (no waiting period stated) for
  Mancozeb 75% **WP** on potato, but 3–5 days for Mancozeb 75% **WG**. Same molecule,
  same crop. Advise the longer, safer figure: **do not harvest within 7 days.**
- ⚠ Toxicity triangle: usually **Green** (comparatively free from danger) on Indian
  mancozeb 75% WP packs — verify on the container.
- REI: not stipulated in India. Practical: re-enter after spray dries.
- Max applications/season: NOT FOUND on the label. Multi-site, low resistance risk;
  Indian potato practice is 6–10 protectant sprays at 7–10 day intervals — that figure is
  extension practice, not a label limit.
- Incompatibility: do **not** mix with alkaline materials, lime sulphur, or Bordeaux.
  Do not mix with copper in the same tank. Decomposes in strongly alkaline water.

**Cymoxanil 8% + Mancozeb 64% WP** (FRAC 27 + M03)
- ⚠ Trade names (not CIB&RC): Curzate M8, Moximate, Sixer (⚠ verify %), Cursor.
- Registered crop/target: Potato — Late blight.
- **Dose: 1500 g formulation/ha (a.i. 1080 g/ha).** Per acre 600 g (derived).
- Water 500–750 L/ha (200–300 L/acre) → **2–3 g/L**. **PHI 10 days.**
- ⚠ Toxicity triangle: commonly **Yellow** (moderately toxic) — verify on pack.
- Max applications: NOT FOUND on label. ⚠ Cymoxanil is a single-site; standard resistance
  guidance is **no more than 3 sprays per season, never two consecutively**, alternated
  with a straight multi-site.
- Incompatibility: not with alkaline materials or copper.

### 1.2 Potato — EARLY BLIGHT (*Alternaria solani*)

| # | Product | Dose/ha | Dose/acre (derived) | Water/ha | Dilution | PHI |
|---|---|---|---|---|---|---|
| 1 | **Mancozeb 75% WP** | 1.5–2.0 kg | 600–800 g | 750 L | 2.0–2.7 g/L | ⚠ "-" |
| 2 | **Chlorothalonil 12.5% + Mancozeb 62.5% WG** | 1.75 kg | 700 g | 500 L | 3.5 g/L | 35 d |
| 3 | **Metiram 70% WG** | 2.0 kg | 810 g | 500–750 L | 2.7–4 g/L | 17 d |
| 4 | **Ziram 80% WP** | 1.5–2.0 kg | 600–800 g | 750–1000 L | 1.5–2.7 g/L | 3 d |
| 5 | **Kresoxim-methyl 44.3% SC** | 500 ml | 200 ml | 500 L | 1 ml/L | 25 d |
| 6 | **Hexaconazole 2% SC** | **3.0 L** | 1.2 L | 500 L | 6 ml/L | 21 d |
| 7 | **Azoxystrobin 13.04% + Thifluzamide 15.66% SC** | 500 ml | 200 ml | 500 L | 1 ml/L | 34 d |
| 8 | **Carbendazim 12% + Mancozeb 63% WP** | 1.75 kg | 700 g | 500 L | 3.5 g/L | 47 d |
| 9 | **Metalaxyl-M 3.9% + Mancozeb 64% WG** | 2.5 kg | 1.0 kg | 500 L | 5 g/L | 32 d |
| 10 | **Copper oxychloride 50% WP** | 2.5 kg | 1.0 kg | 750–1000 L | 2.5–3.3 g/L | ⚠ "-" |
| 11 | **Kasugamycin 3% SL** | 1.0–1.5 L | 400–600 ml | 500 L | 2–3 ml/L | 8 d |
| 12 | **Copper Sulphate 2.62% SC** | 1.0 L | 400 ml | 500 L | 2 ml/L | 3 d |

⚠ **Note the Hexaconazole 2% SC dose — 3.0 litres/ha.** It is a very dilute formulation.
Do not carry the "Hexaconazole 5% EC @ 400 ml/ha" figure across; different product.

> **NOT REGISTERED — Difenoconazole 25% EC on potato.** Difenoconazole is heavily
> recommended in the field for potato early blight and appears on onion, chilli, tomato
> and several other crops in the CIB&RC list — but **there is no potato entry** as on
> 31.03.2026. Recommending it on potato is off-label. Use Chlorothalonil+Mancozeb,
> Metiram, or Kresoxim-methyl instead.

---

## 2. ONION

### 2.1 Onion — PURPLE BLOTCH (*Alternaria porri*) [+ Stemphylium blight]

**Critical spray note:** onion leaves are waxy and vertical. **A non-ionic
spreader-sticker is essential** or most of the spray runs off. This is standard SAU
advice; the sticker rate is not part of the fungicide registration.

| # | Product | Dose/ha | Dose/acre (derived) | Water/ha | Dilution | PHI |
|---|---|---|---|---|---|---|
| 1 | **Difenoconazole 25% EC** | 500 ml | 200 ml | 500 L | **1 ml/L (0.1%, label)** | 20 d |
| 2 | **Tebuconazole 25.9% EC** | 625–750 ml | 250–300 ml | 500 L | 1.25–1.5 ml/L | 21 d |
| 3 | **Metiram 70% WG** | 1.25–1.5 kg | 500–600 g | 500 L | 2.5–3 g/L | 7 d |
| 4 | **Azoxystrobin 18.2% + Difenoconazole 11.4% SC** | 500 ml | 200 ml | 500 L | **1 ml/L (0.1%, label)** | 7 d |
| 5 | **Azoxystrobin 8.3% + Mancozeb 66.7% WG** | 1.5 kg | 600 g | 500 L | 3 g/L | 42 d |
| 6 | **Difenoconazole 4.8% + Mancozeb 64% WP** | 1.75–2.0 kg | 700–810 g | 500 L | 3.5–4 g/L | 20 d |
| 7 | **Tebuconazole 50% + Trifloxystrobin 25% WG** | 300 g | 120 g | 500 L | 0.6 g/L | 29 d |
| 8 | **Fluopyram 21.37% + Trifloxystrobin 21.37% SC** | 500–600 ml | 200–240 ml | 500 L | 1–1.2 ml/L | 30 d |
| 9 | **Metiram 55% + Pyraclostrobin 5% WG** | 1.5–1.75 kg | 600–700 g | 500 L | 3–3.5 g/L | 16 d |
| 10 | **Picoxystrobin 7.05% + Propiconazole 11.7% SC** | 1.0 L | 400 ml | 500 L | 2 ml/L | 30 d |
| 11 | **Boscalid 25.2% + Pyraclostrobin 12.8% WG** | 500 g | 200 g | 500 L | 1 g/L | 24 d |
| 12 | **Fluxapyroxad 250 g/L + Pyraclostrobin 250 g/L SC** | 250 ml | 100 ml | 500 L | 0.5 ml/L | 10 d |
| 13 | **Tebuconazole 38.39% SC** | 440–500 ml | 178–202 ml | 375–500 L | ~1 ml/L | 43 d |
| 14 | **Metalaxyl-M 3.3% + Chlorothalonil 33.1% SC** | ~1.0–1.25 L | 400–500 ml | 500 L | **2 ml/L (label)** | 10 d |

**Product detail:**

**Difenoconazole 25% EC** (triazole, FRAC 3)
- ⚠ Trade names (not CIB&RC): Score, Scoret, Dizone, Difender, Sitara.
- Registered crop/target: **Onion — Purple blotch.**
- **Registered dose expressed as concentration: 0.1% = 100 ml per 100 L water**, with a
  registered spray volume of 500 L/ha → **500 ml/ha = 200 ml/acre (derived).**
- **PHI 20 days.** This matters: 20 days before bulb harvest is the cut-off.
- ⚠ Toxicity triangle: typically **Yellow** — verify on pack.
- REI: not stipulated in India.
- Max applications: NOT FOUND on label. ⚠ FRAC anti-resistance practice for a DMI:
  max 2–3 per season, alternate with a non-triazole.
- Incompatibility: EC formulation — do not mix with strongly alkaline products or with
  copper. Jar-test before mixing with any WG.

> ⚠ **IMPORTANT DISCREPANCY — Mancozeb alone on onion.**
> Straight Mancozeb 75% WP/WG has **NO onion entry** in the CIB&RC list as on 31.03.2026,
> yet "Mancozeb 0.25% for purple blotch" is one of the most common SAU/extension
> recommendations in India. Mancozeb reaches onion legally **only inside a registered
> combination** (rows 5, 6, 14 above). Flag any straight-mancozeb-on-onion advice as
> **NOT REGISTERED**. Zineb 75% WP *is* registered on onion but for **downy mildew and
> blight**, at 1.5–2.0 kg/ha in 750–1000 L water — not for purple blotch specifically.

### 2.2 Onion — THRIPS (*Thrips tabaci*)

Source: CIB&RC MUP Insecticides 31.03.2026 —
https://ppqs.gov.in/sites/default/files/updated_mup_insecticide_as_on_31.03.2026_c.pdf

| # | Product | Dose/ha | Dose/acre (derived) | Water/ha | Dilution | PHI |
|---|---|---|---|---|---|---|
| 1 | **Fipronil 5% SC** | ⚠ **NOT FOUND for onion** — registered on chilli/cotton/sugarcane, not onion | — | — | — | — |
| 2 | **Fipronil 80% WG** | 75 g | 30 g | 500 L | 0.15 g/L | 15 d |
| 3 | **Lambda-cyhalothrin 5% EC** | 300 ml | 120 ml | 300–400 L | 0.75–1.0 ml/L | 5 d |
| 4 | **Tolfenpyrad 15% EC** | 1000 ml | 400 ml | 500 L | 2 ml/L | 10 d |
| 5 | **Deltamethrin 11% w/w EC** | 150 ml | 60 ml | 500 L | 0.3 ml/L | 5 d |
| 6 | **Fipronil 12.5% + Lambda-cyhalothrin 5% ZC** | 400 ml | 162 ml | 500 L | 0.8 ml/L | 7 d |
| 7 | **Profenofos 50% EC** | 1000 ml | 400 ml | 500 L | 2 ml/L | **80 d** ⚠ |
| 8 | **Oxydemeton-methyl 25% EC** | 1200 ml | 486 ml | 500–1000 L | 1.2–2.4 ml/L | ⚠ "-" |

⚠ **Profenofos on onion carries an 80-day waiting period.** In a 100–130 day onion crop
that effectively restricts it to very early vegetative stage only. Never recommend it
close to bulb maturity.

**Fipronil 80% WG** (phenylpyrazole, IRAC 2B)
- ⚠ Trade names (not CIB&RC): Regent Ultra, Jump 80, Fipro 80.
- Registered: **Onion — Thrips. 75 g formulation/ha (60 g a.i./ha) = 30 g/acre (derived),
  in 500 L water/ha, PHI 15 days.**
- ⚠ Toxicity triangle: fipronil formulations commonly **Yellow**; the technical is highly
  toxic. Verify on the pack.
- Max applications: NOT FOUND. ⚠ Do not exceed 2 fipronil sprays per season — thrips
  resistance to fipronil is already documented in Indian onion belts.
- Incompatibility: highly toxic to bees and to fish. Do not spray on flowering
  intercrops; do not let wash-water enter ponds.

> ⚠ **Spinosad and Spinetoram are NOT REGISTERED on onion** in the CIB&RC list, despite
> being routinely recommended for onion thrips. Mark as off-label.

---

## 3. CHILLI

### 3.1 Chilli — ANTHRACNOSE / FRUIT ROT / DIE-BACK (*Colletotrichum capsici*)

| # | Product | Registered target wording | Dose/ha | Dose/acre (derived) | Water/ha | Dilution | PHI |
|---|---|---|---|---|---|---|---|
| 1 | **Difenoconazole 25% EC** | Die-back, Fruit rot | 250–500 ml | 100–200 ml | 500–1000 L | **0.5 ml/L (0.05%, label)** | 15 d |
| 2 | **Chlorothalonil 75% WP** | Fruit rot | 800 g | 325 g | 750 L | ~1.1 g/L | 10 d |
| 3 | **Captan 50% WG** | Fruit rot (Anthracnose) | 1500 g | 600 g | 500 L | 3 g/L | 5 d |
| 4 | **Copper hydroxide 53.8% DF** | Anthracnose | 1000 g | 400 g | 500 L | 2 g/L | 5 d |
| 5 | **Copper hydroxide 61.41% WG** | Anthracnose | 875 g | 355 g | 500 L | 1.75 g/L | 3 d |
| 6 | **Pyraclostrobin 20% WG** | Anthracnose | 500 g | 200 g | 500 L | 1 g/L | 3 d |
| 7 | **Metiram 70% WG** | Anthracnose | 2.0 kg | 810 g | 500 L | 4 g/L | 10 d |
| 8 | **Hexaconazole 75% WG** | Leaf spot, anthracnose, powdery mildew | 66.7 g | 27 g | 500 L | 0.13 g/L | 7 d |
| 9 | **Tebuconazole 25.9% EC** | Fruit rot, powdery mildew | 500–750 ml | 200–300 ml | 500 L | 1–1.5 ml/L | 5 d |
| 10 | **Kresoxim-methyl 44.3% SC** | Powdery mildew, fruit rot, **die-back**, twig blight | 500 ml | 200 ml | 500 L | 1 ml/L | 25 d |
| 11 | **Propineb 70% WP** | Die-back | 500 g/100 L (0.5%) | — | as required | **5 g/L (label)** | 10 d |
| 12 | **Kasugamycin 3% SL** | Bacterial leaf spot, Cercospora leaf spot, **die-back** | 1.0–1.25 L | 400–500 ml | 375–500 L | 2.5 ml/L | 5 d |
| 13 | **Copper sulphate pentahydrate 6% SC** | Anthracnose, leaf spot, fruit rot | 1250 ml | 500 ml | 500 L | 2.5 ml/L | 7 d |
| 14 | **Copper oxychloride 50% WP** | Leaf spot, fruit rot | 2.5 kg | 1.0 kg | 750–1000 L | 2.5–3.3 g/L | ⚠ "-" |

⚠ **Captan warning:** never apply Captan within 10–14 days of an oil spray, and never mix
with alkaline materials — severe fruit and foliage burn on chilli.

⚠ **Kresoxim-methyl PHI is 25 days.** Chilli is picked repeatedly; this product is only
usable well before the first picking. For a crop already in picking, use Pyraclostrobin
(3 d), Copper hydroxide 61.41% WG (3 d), Tebuconazole (5 d) or Captan (5 d).

### 3.2 Chilli — THRIPS

| # | Product | Dose/ha | Dose/acre (derived) | Water/ha | Dilution | PHI |
|---|---|---|---|---|---|---|
| 1 | **Fipronil 5% SC** | 800–1000 ml | 325–400 ml | 500 L | 1.6–2 ml/L | 7 d |
| 2 | **Fipronil 80% WG** | 50–62.5 g | 20–25 g | 500 L | 0.1–0.125 g/L | 5 d |
| 3 | **Spinetoram 11.7% SC** | 470–500 ml | 190–200 ml | 400–500 L | ~1 ml/L | 7 d |
| 4 | **Spinosad 45% SC** | 160 ml | 65 ml | 500 L | 0.32 ml/L | 3 d |
| 5 | **Cyantraniliprole 10.26% OD** | 600 ml | 240 ml | 500 L | 1.2 ml/L | 3 d |
| 6 | **Fluxametamide 10% EC** | 400 ml | 162 ml | 500 L | 0.8 ml/L | 5 d |
| 7 | **Flometoquin 10% SC** | 750–1000 ml | 300–400 ml | 500 L | 1.5–2 ml/L | 10 d |
| 8 | **Tolfenpyrad 15% EC** | 1000 ml | 400 ml | 500 L | 2 ml/L | 7 d |
| 9 | **Acetamiprid 20% SP** | 50–100 g | 20–40 g | 500–600 L | ~0.17 g/L | 3 d |
| 10 | **Spirotetramat 15.31% OD** | 400 ml | 162 ml | 500 L | 0.8 ml/L | 5 d |
| 11 | **Thiacloprid 21.7% SC** | 225–300 ml | 90–120 ml | 500 L | 0.45–0.6 ml/L | 5 d |
| 12 | **Broflanilide 300 g/L SC** | 42–62 ml | 17–25 ml | 500 L | ~0.1 ml/L | 1 d |
| 13 | **Emamectin benzoate 5% SG** | 200 g | 81 g | 500 L | 0.4 g/L | 3 d |
| 14 | **Profenofos 50% EC** | 1000 ml | 400 ml | 500 L | 2 ml/L | 3 d |

⚠ **Black thrips (*Thrips parvispinus*)** — the species that devastated chilli from 2021
onwards — is named on **only one** CIB&RC entry:
**Spiromesifen 15% + Hexythiazox 2.2% + Abamectin 1.15% SC @ 625 ml/ha (253 ml/acre
derived), 500 L water/ha, PHI 16 days**, registered for "Yellow mites
(*Polyphagotarsonemus latus*) and **Black thrips (*Thrips parvispinus*)**".
Everything else above is registered against *Scirtothrips dorsalis* or *Thrips tabaci*.
Using them against *parvispinus* is a species mismatch, not a crop mismatch — legal, but
efficacy data does not exist for that species. **Flag this to the farmer.**

### 3.3 Chilli — YELLOW MITE (*Polyphagotarsonemus latus*)

| # | Product | Dose/ha | Dose/acre (derived) | Water/ha | Dilution | PHI |
|---|---|---|---|---|---|---|
| 1 | **Fenazaquin 10% EC** | 1250 ml | 500 ml | 400–600 L | 2.1–3.1 ml/L | 10 d |
| 2 | **Fenazaquin 18.3% SC** | 625 ml | 253 ml | 500 L | 1.25 ml/L | 10 d |
| 3 | **Fenpyroximate 5% EC** | 300–600 ml | 120–240 ml | 300–500 L | ~1.2 ml/L | 7 d |
| 4 | **Fenpyroximate 5% SC** | 300–600 ml | 120–240 ml | 500–750 L | ~0.8 ml/L | 3 d |
| 5 | **Hexythiazox 5.45% EC** | 300–500 ml | 120–200 ml | 625 L | 0.5–0.8 ml/L | 3 d |
| 6 | **Spiromesifen 22.9% SC** | 400 ml | 162 ml | 500–750 L | 0.5–0.8 ml/L | 7 d |
| 7 | **Milbemectin 1% EC** | 325 ml | 132 ml | 500 L | 0.65 ml/L | 7 d |
| 8 | **Pyridaben 20% WP** | 375–500 g | 152–202 g | 500 L | 0.75–1 g/L | 5 d |
| 9 | **Propargite 57% EC** | 1500 ml | 607 ml | 500–625 L | 2.4–3 ml/L | 7 d |
| 10 | **Cyenopyrafen 30% SC** | 200–300 ml | 81–121 ml | 400–600 L | ~0.5 ml/L | 7 d |
| 11 | **Isocycloseram 9.2% DC** | 200 ml | 81 ml | 500 L | 0.4 ml/L | 7 d |
| 12 | **Diafenthiuron 50% WP** | 600 g | 243 g | 500–750 L | 0.8–1.2 g/L | 3 d |
| 13 | **Ethion 50% EC** | 1500–2000 ml | 607–809 ml | 500–1000 L | 1.5–4 ml/L | 5 d |
| 14 | **Propargite 42% + Hexythiazox 2% EC** | 1250 ml | 506 ml | 500 L | 2.5 ml/L | 7 d |

⚠ **Propargite is phytotoxic to chilli under high temperature and on tender new growth.**
Do not spray above ~35 °C or on a crop under moisture stress. Do not use on seedlings.
⚠ **Mite resistance:** hexythiazox and spiromesifen are growth/lipid inhibitors — one
application per season each, then rotate to a different IRAC group (fenazaquin = 21A,
fenpyroximate = 21A, propargite = 12C, spiromesifen = 23, hexythiazox = 10A). Note
fenazaquin and fenpyroximate are the **same** IRAC group 21A — rotating between them is
not a real rotation.

---

## 4. OKRA (Bhindi)

### 4.1 Okra — SHOOT AND FRUIT BORER (*Earias vittella*)

| # | Product | Dose/ha | Dose/acre (derived) | Water/ha | Dilution | PHI |
|---|---|---|---|---|---|---|
| 1 | **Flubendiamide 39.35% SC** | 100–125 ml | 40–50 ml | 500 L | 0.2–0.25 ml/L | **3 d** |
| 2 | **Chlorantraniliprole 18.5% SC** | 125 ml | 50 ml | 500 L | 0.25 ml/L | **5 d** |
| 3 | **Emamectin benzoate 5% SG** | 135–170 g | 55–69 g | 500 L | 0.27–0.34 g/L | **5 d** |
| 4 | **Spinetoram 11.7% SC** | 375–450 ml | 152–182 ml | 500–1000 L | 0.4–0.9 ml/L | **3 d** |
| 5 | **Pyridalyl 10% EC** | 500–750 ml | 202–304 ml | 500–750 L | 1 ml/L | 3 d |
| 6 | **Cypermethrin 25% EC** | 150–200 ml | 60–81 ml | 500 L | 0.3–0.4 ml/L | 3 d |
| 7 | **Deltamethrin 2.8% EC** | 400–600 ml | 162–243 ml | 400–600 L | 1 ml/L | **1 d** |
| 8 | **Deltamethrin 11% EC** | 100–125 ml | 40–50 ml | 375–500 L | 0.25 ml/L | 3 d |
| 9 | **Quinalphos 20% AF** | 1250–1500 ml | 506–607 ml | 750–1000 L | 1.5 ml/L | 7 d |
| 10 | **Fenvalerate 20% EC** | 300–375 ml | 121–152 ml | 600–750 L | 0.5 ml/L | 7 d |
| 11 | **Chlorantraniliprole 9.3% + Lambda-cyhalothrin 4.6% ZC** | 200 ml | 81 ml | 500 L | 0.4 ml/L | 3 d |
| 12 | **Cyantraniliprole 10.26% OD** | 900 ml | 364 ml | 500 L | 1.8 ml/L | 3 d |
| 13 | **Broflanilide 20% SC** | 125 ml | 50 ml | 500 L | 0.25 ml/L | **1 d** |

**Okra is picked every 2–3 days.** The PHI column is therefore the single most important
number on this page. Prefer Broflanilide (1 d), Deltamethrin 2.8% EC (1 d),
Flubendiamide (3 d), Spinetoram (3 d), Pyridalyl (3 d). Advise the farmer to **pick the
crop clean first, then spray**, and observe the PHI before the next picking.

**Flubendiamide 39.35% SC** (diamide, IRAC 28)
- ⚠ Trade names (not CIB&RC): Fame, Takumi (⚠ verify %), Flubendia.
- Registered: **Okra — Shoot & fruit borer. 100–125 ml/ha (48–60 g a.i./ha)
  = 40–50 ml/acre (derived), 500 L water/ha (200 L/acre) → 0.2–0.25 ml/L. PHI 3 days.**
- ⚠ Toxicity triangle: usually **Green/Blue** (low mammalian toxicity) — verify on pack.
- REI: not stipulated. Max applications: NOT FOUND on the label. ⚠ Diamide resistance in
  *Earias*/*Helicoverpa* is rising; limit to 2 sprays per season and do not follow with
  chlorantraniliprole (same IRAC group 28).
- Incompatibility: no specific label restriction found. Jar-test with EC products.

### 4.2 Okra — JASSID / LEAFHOPPER (*Amrasca biguttula biguttula*)

| # | Product | Dose/ha | Dose/acre (derived) | Water/ha | Dilution | PHI |
|---|---|---|---|---|---|---|
| 1 | **Imidacloprid 17.8% SL** | 100 ml | 40 ml | 500 L | 0.2 ml/L | 3 d |
| 2 | **Imidacloprid 70% WG** | 30–35 g | 12–14 g | 300–375 L | 0.1 g/L | 3 d |
| 3 | **Thiamethoxam 25% WG** | 100 g | 40 g | 500–1000 L | 0.1–0.2 g/L | 5 d |
| 4 | **Flonicamid 50% WG** | 200 g | 81 g | 500 L | 0.4 g/L | 10 d |
| 5 | **Diafenthiuron 50% WP** | 600 g | 243 g | 500 L | 1.2 g/L | 5 d |
| 6 | **Flupyradifurone 17.09% SL** | 1250 ml | 506 ml | 500 L | 2.5 ml/L | 3 d |
| 7 | **Tolfenpyrad 15% EC** | 1000 ml | 400 ml | 500 L | 2 ml/L | 3 d |
| 8 | **Fluxametamide 10% EC** | 400 ml | 162 ml | 500 L | 0.8 ml/L | 5 d |
| 9 | **Lambda-cyhalothrin 5% EC** | 300 ml | 121 ml | 300–400 L | 0.75–1 ml/L | 4 d |
| 10 | **Cypermethrin 25% EC** | 150–200 ml | 60–81 ml | 500 L | 0.3–0.4 ml/L | 3 d |
| 11 | **Buprofezin 15% + Acephate 35% WP** | 750 g | 304 g | 500 L | 1.5 g/L | 7 d |
| 12 | **Pyriproxyfen 10% EC** | 500 ml | 202 ml | 300 L | 1.7 ml/L | 7 d |
| 13 | **Broflanilide 20% SC** | 125 ml | 50 ml | 500 L | 0.25 ml/L | 1 d |

**Seed treatment (registered, prevents the first 25–30 days of jassid attack):**
- **Imidacloprid 48% FS — 500–900 ml per 100 kg seed** (300–540 g a.i./100 kg). PHI: NA.
- **Imidacloprid 70% WS — 350–700 g per 100 kg seed.** PHI: NA.
- **Thiamethoxam 70% WS — 286 g per 100 kg seed** (200 g a.i.). Applied at sowing.
- **Thiamethoxam 30% FS — 5.7 ml per kg seed** (1.7 g a.i.), used as seed dresser.

⚠ Neonicotinoid seed treatment plus a neonicotinoid foliar spray in the same crop is
double-dosing the **same IRAC group 4A** and is the fastest route to jassid resistance.
If seed was treated, make the first foliar spray a **different** group — flonicamid (29),
diafenthiuron (12A), or tolfenpyrad (21A).

---

## 5. BRINJAL

### 5.1 Brinjal — SHOOT AND FRUIT BORER (*Leucinodes orbonalis*)

**Read this before recommending anything:** BSFB is the crop where Indian farmers spray
most often and most dangerously — 15–40 sprays per season is documented. The registered
chemistry below works only alongside **weekly clipping and destruction of wilted shoots**
and **pheromone traps at 20–25/ha**. Chemical-only control fails and drives residues.

| # | Product | Dose/ha | Dose/acre (derived) | Water/ha | Dilution | PHI |
|---|---|---|---|---|---|---|
| 1 | **Emamectin benzoate 5% SG** | 200 g | 81 g | 500 L | 0.4 g/L | **3 d** |
| 2 | **Spinosad 45% SC** | 162–187 ml | 66–76 ml | 500 L | 0.32–0.37 ml/L | **3 d** |
| 3 | **Spinetoram 11.7% SC** | 375–450 ml | 152–182 ml | 500–1000 L | 0.4–0.9 ml/L | **3 d** |
| 4 | **Flubendiamide 39.35% SC** | 150–187.5 ml | 61–76 ml | 500 L | 0.3–0.37 ml/L | 5 d |
| 5 | **Chlorantraniliprole 18.5% SC** | 200 ml | 81 ml | 500–750 L | 0.27–0.4 ml/L | **22 d** ⚠ |
| 6 | **Cypermethrin 25% EC** | 150–200 ml | 60–81 ml | 500 L | 0.3–0.4 ml/L | **1 d** |
| 7 | **Deltamethrin 2.8% EC** | 400–500 ml | 162–202 ml | 500 L | 0.8–1 ml/L | 3 d |
| 8 | **Thiodicarb 75% WP** | 625–1000 g | 253–405 g | 500 L | 1.25–2 g/L | 6 d |
| 9 | **Carbosulfan 25% EC** | 1250 ml | 506 ml | 500 L | 2.5 ml/L | 5 d |
| 10 | **Thiacloprid 21.7% SC** | 750 ml | 304 ml | 500 L | 1.5 ml/L | 5 d |
| 11 | **Novaluron 5.25% + Emamectin benzoate 0.9% SC** | 1500 ml | 607 ml | 500 L | 3 ml/L | 5 d |
| 12 | **Broflanilide 300 g/L SC** | 42–62 ml | 17–25 ml | 500 L | ~0.1 ml/L | **1 d** |
| 13 | **Chlorpyrifos 20% EC** | 1000 ml | 405 ml | 500–1000 L | 1–2 ml/L | ⚠ "-" |
| 14 | **Fluxametamide 10% EC** | 400 ml | 162 ml | 500 L | 0.8 ml/L | 5 d |

⚠ **Chlorantraniliprole 18.5% SC has a 22-day PHI on brinjal**, versus 5 days on okra.
Brinjal is picked every 4–7 days. This product is realistically only usable **before
fruiting begins**. This is exactly the kind of label detail farmers are never told, and
is a strong reason the advisory device should surface PHI first, not last.

**Emamectin benzoate 5% SG** (avermectin, IRAC 6)
- ⚠ Trade names (not CIB&RC): Proclaim, Missile, Starclaim, EM-1, Emmaa.
- Registered: **Brinjal — Fruit and shoot borer. 200 g/ha (10 g a.i./ha) = 81 g/acre
  (derived), 500 L water/ha (200 L/acre) → 0.4 g/L. PHI 3 days.**
- ⚠ Toxicity triangle: commonly **Yellow** — verify on pack.
- REI: not stipulated. Max applications: NOT FOUND on label.
- Incompatibility: do not mix with strongly alkaline materials (Bordeaux, lime).
  Highly toxic to bees — do not spray during flowering hours; spray late evening.

---

## 6. COTTON

### 6.1 Cotton — PINK BOLLWORM (*Pectinophora gossypiella*)

**Spraying is the last line, not the first.** PBW is controlled in India primarily by:
timely sowing and a **strict end to the crop by December–January** (no extended/ratoon
cotton), pheromone trap monitoring (**ETL = 8 moths/trap/night for 3 consecutive nights**,
or 10% rosette flowers, or 2 live larvae/20 green bolls), and mass trapping/PBKnot mating
disruption. Sprays before ETL simply select for resistance.

| # | Product | Dose/ha | Dose/acre (derived) | Water/ha | Dilution | PHI |
|---|---|---|---|---|---|---|
| 1 | **Cyantraniliprole 16.9% + Lufenuron 16.9% SC** | 250 ml | 101 ml | 500 L | 0.5 ml/L | 25 d |
| 2 | **Quinalphos 20% AF** | 1750–2500 ml | 708–1012 ml | 750–1000 L | ~2.5 ml/L | 7 d |
| 3 | **Fenpropathrin 30% EC** | 250–340 ml | 101–138 ml | 750–1000 L | 0.34 ml/L | 14 d |
| 4 | **Fenpropathrin 10% EC** | 750–1000 ml | 304–405 ml | 750–1000 L | 1 ml/L | 14 d |
| 5 | **Cypermethrin 10% EC** | 550–760 ml | 223–308 ml | 150–1000 L | varies | 7 d |
| 6 | **Spinetoram 11.7% SC** | 450 ml | 182 ml | 500–1000 L | 0.45–0.9 ml/L | ⚠ not stated |
| 7 | **Profenofos 50% + Fenpropathrin 5% EC** | 1500 ml | 607 ml | 500 L | 3 ml/L | 22 d |
| 8 | **Chlorpyriphos 50% + Cypermethrin 5% EC** | 1000 ml | 405 ml | 500–1000 L | 1–2 ml/L | 15 d |
| 9 | **Chlorpyriphos 16% + Alphacypermethrin 1% EC** | 2500 ml | 1012 ml | 500–750 L | 3.3–5 ml/L | 15 d |
| 10 | **Bifenthrin 25% + Thiamethoxam 25% WG** | 200 g | 81 g | 500 L | 0.4 g/L | 42 d |
| 11 | **Acetamiprid 25% + Bifenthrin 25% WG** | 160 g | 65 g | 500 L | 0.32 g/L | 33 d |
| 12 | **Cyantraniliprole 7.3% + Diafenthiuron 36.4% SC** | 625 ml | 253 ml | 500 L | 1.25 ml/L | 29 d |
| 13 | **Chlorantraniliprole 12% + Fipronil 30% GR** | 250 g | 101 g | 500 L | — | 41 d |

⚠ **Synthetic pyrethroids (cypermethrin, fenpropathrin, bifenthrin) resurge whitefly and
aphid.** Restrict them to the **late boll-formation stage only**, never early season, and
never more than 2 pyrethroid sprays in the whole crop. This is standard Indian cotton IPM
policy and the reason for the 2015–2017 whitefly outbreaks in Punjab.

### 6.2 Cotton — JASSID / LEAFHOPPER (*Amrasca biguttula biguttula*)

| # | Product | Dose/ha | Dose/acre (derived) | Water/ha | Dilution | PHI |
|---|---|---|---|---|---|---|
| 1 | **Imidacloprid 17.8% SL** | 100–125 ml | 40–51 ml | 500–700 L | 0.2 ml/L | 40 d |
| 2 | **Imidacloprid 70% WG** | 30–35 g | 12–14 g | 375–500 L | 0.07–0.09 g/L | 7 d |
| 3 | **Acetamiprid 20% SP** | 50 g | 20 g | 500–600 L | 0.09 g/L | 15 d |
| 4 | **Flonicamid 50% WG** | 150 g | 61 g | 500 L | 0.3 g/L | 25 d |
| 5 | **Diafenthiuron 50% WP** | 600 g | 243 g | 500–1000 L | 0.6–1.2 g/L | 21 d |
| 6 | **Diafenthiuron 47.8% SC** | 500 ml | 202 ml | 500 L | 1 ml/L | 41 d |
| 7 | **Dinotefuran 20% SG** | 125–150 g | 51–61 g | 500 L | 0.25–0.3 g/L | 15 d |
| 8 | **Clothianidin 50% WDG** | 30–40 g | 12–16 g | 500 L | 0.06–0.08 g/L | 20 d |
| 9 | **Fipronil 5% SC** | 1500–2000 ml | 607–809 ml | 500 L | 3–4 ml/L | 6 d |
| 10 | **Afidopyropen 50 g/L DC** | 1000 ml | 405 ml | 500–750 L | 1.3–2 ml/L | 25 d |
| 11 | ~~Flupyradifurone 17.09% SL~~ | **NOT REGISTERED on cotton** — verified: its only CIB&RC entries are **Okra** (jassid/whitefly) and **Tea** (mosquito bug) | — | — | — | — |
| 12 | **Acephate 75% SP** | 390 g | 158 g | 500–1000 L | 0.4–0.8 g/L | 15 d |
| 13 | **Dimethoate 30% EC** | 660 ml | 267 ml | 500–1000 L | 0.7–1.3 ml/L | 24 d |
| 14 | **Isocycloseram 9.2% DC** | 200 ml | 81 ml | 500 L | 0.4 ml/L | 37 d |

**Seed treatment (registered):** Imidacloprid 48% FS @ 500–900 ml/100 kg seed, or
Imidacloprid 70% WS @ 500–1000 g/100 kg seed, or Carbosulfan 25% DS @ 60 g/kg seed.
These give ~30–40 days protection; **do not add a neonicotinoid foliar spray on top.**

---

## 7. SUGARCANE

### 7.1 Sugarcane — EARLY SHOOT BORER (*Chilo infuscatellus*)

| # | Product | Dose/ha | Dose/acre (derived) | Water/ha | Dilution | PHI |
|---|---|---|---|---|---|---|
| 1 | **Chlorantraniliprole 18.5% SC** | 375 ml | 152 ml | 1000 L | 0.375 ml/L | **208 d** |
| 2 | **Chlorantraniliprole 0.4% GR** | 18.75 kg (broadcast) | 7.6 kg | — | — | 147 d |
| 3 | **Chlorantraniliprole 47.85% SC** | 125 ml | 51 ml | 1000 L | 0.125 ml/L | 214 d |
| 4 | **Flubendiamide 20% WG** | 375 g | 152 g | 500–750 L | 0.5–0.75 g/L | 204 d |
| 5 | **Fipronil 5% SC** | 1500–2000 ml | 607–809 ml | 500 L | 3–4 ml/L | 270 d |
| 6 | **Fipronil 0.3% GR** | 25–33.3 kg | 10.1–13.5 kg | soil, no water | — | ⚠ printed "09" — implausible; verify |
| 7 | **Fipronil 0.6% GR** | 12.5 kg | 5.1 kg | soil | — | 229 d |
| 8 | **Chlorpyrifos 20% EC** | 1250–1500 ml | 506–607 ml | 500–1000 L | 1.5 ml/L | ⚠ "-" |
| 9 | **Methoxyfenozide 21.8% SC** | 500–625 ml | 202–253 ml | 500 L | 1–1.25 ml/L | 161 d |
| 10 | **Thiamethoxam 75% SG** | 160 g | 65 g | 500–1000 L | 0.16–0.32 g/L | 230 d |
| 11 | **Bifenthrin 8% + Clothianidin 10% SC** | 1000 ml | 405 ml | 1000 L | 1 ml/L | 300 d |
| 12 | **Chlorantraniliprole 15.75% + Clothianidin 26.25% SC** | 400 ml | 162 ml | 1000 L | 0.4 ml/L | 258 d |
| 13 | **Chlorantraniliprole 0.4% + Fipronil 0.6% + Clothianidin 1.0% GR** | 10 kg | 4.05 kg | soil | — | 156 d |

The very long PHIs (150–300 days) are not a restriction in practice — sugarcane is a
10–12 month crop and ESB is controlled in the **first 60 days after planting**. Granular
formulations are applied to the furrow/soil at planting or at earthing-up, then irrigated.

⚠ **Fipronil 0.3% GR is printed with a 9-day waiting period** in the CIB&RC table while
every other fipronil sugarcane entry is 229–270 days. This is almost certainly a
typographical error in the source. **NOT RELIABLE — requires verification against the
container label.** Do not build an advisory on it.

### 7.2 Sugarcane — RED ROT (*Colletotrichum falcatum*)

> **Red rot cannot be cured by any fungicide once the cane is infected.** The disease is
> managed by: resistant varieties (the primary and effectively only real control),
> disease-free seed cane from a nursery, **roguing and burning** infected clumps,
> avoiding ratooning an infected field, and crop rotation with rice/other non-hosts.

**The ONLY chemical registered on sugarcane for red rot as on 31.03.2026:**

**Azoxystrobin 18.2% + Difenoconazole 11.4% w/w SC**
- Registered crop/target: **Sugarcane — Red rot, Smut and Rust.**
- **Dose: 0.1% = 1 ml per litre of water**, a.i. 0.03% (0.3 g/L).
  Registered spray volume **400 L/ha** → **≈400 ml/ha = 162 ml/acre (derived).**
- **PHI 265 days.**
- ⚠ Toxicity triangle: not established here — read the pack.
- REI / max applications / incompatibility: NOT FOUND.
- Source: CIB&RC MUP Fungicides 31.03.2026, p.45 (combination-products section).

> ⚠ **NOT REGISTERED — Carbendazim sett treatment on sugarcane.** "Dip setts in
> carbendazim 0.1% for 10–15 minutes" is one of the most widely repeated Indian
> recommendations for red rot and is in numerous SAU packages, **but carbendazim has no
> sugarcane entry in the CIB&RC Major Uses list as on 31.03.2026.** Likewise
> **moist hot air treatment (MHAT) at 54 °C for 4 hours** and **aerated steam therapy**
> are the non-chemical sett treatments actually recommended by ICAR-SBI Coimbatore and
> carry no registration issue. Prefer those. Flag any carbendazim sett-dip advice as
> off-label.

---

## 8. GROUNDNUT

### 8.1 Groundnut — LATE LEAF SPOT & RUST

⚠ **Terminology, and it matters.** CIB&RC labels almost always say **"Tikka leaf spot"**,
which is the Indian trade term covering **both** early leaf spot (*Cercospora
arachidicola*) and late leaf spot (*Phaeoisariopsis / Nothopassalora personata*). Only
**two** registrations name late leaf spot explicitly (rows 12 and 13 below). Everything
else registered for "Tikka" legally covers the late leaf spot use. Rust
(*Puccinia arachidis*) is named separately and not every Tikka product carries it —
check the crop/target column before recommending for rust.

| # | Product | Registered target | Dose/ha | Dose/acre (derived) | Water/ha | Dilution | PHI |
|---|---|---|---|---|---|---|---|
| 1 | **Mancozeb 75% WP** | Tikka **and** rust | 1.5–2.0 kg | 600–800 g | 750 L | 2–2.7 g/L | ⚠ "-" |
| 2 | **Chlorothalonil 75% WP** | Tikka leaf spot **and** rust | 0.88–1.15 kg | 356–465 g | 600–800 L | ~1.5 g/L | 14 d |
| 3 | **Tebuconazole 25% WG** | Tikka leaf spot, rust | 500–750 g | 202–304 g | 500 L | 1–1.5 g/L | 22 d |
| 4 | **Tebuconazole 25.9% EC** | Tikka **and** rust | 500–750 ml | 202–304 ml | 500 L | 1–1.5 ml/L | **49 d** ⚠ |
| 5 | **Hexaconazole 5% EC** | Tikka leaf spot | 1500 ml | 607 ml | 500 L | 3 ml/L | 30 d |
| 6 | **Hexaconazole 75% WG** | Tikka leaf spot, rust | 66.7 g | 27 g | 500 L | 0.13 g/L | 31 d |
| 7 | **Propiconazole 25% EC** | Early leaf spot **and** rust | 500 ml | 202 ml | 750 L | 0.67 ml/L | 15 d |
| 8 | **Difenoconazole 25% EC** | Leaf spot, rust | 0.1% (100 ml/100 L) | — | as required | **1 ml/L (label)** | 34 d |
| 9 | **Bitertanol 25% WP** | Rust **and** Tikka (separate rows) | 1000 g | 405 g | 500 L | 2 g/L | 30 d |
| 10 | **Carbendazim 50% WP** | Tikka leaf spot | 225 g | 91 g | 750 L | 0.3 g/L | ⚠ "-" |
| 11 | **Pyraclostrobin 20% WG** | Tikka disease | 500 g | 202 g | 500 L | 1 g/L | 29 d |
| 12 | **Prochloraz 34.8% + Propiconazole 7.8% EC** | **Early leaf spot, LATE leaf spot, Rust** | 750 ml | 304 ml | 500 L | 1.5 ml/L | 19 d |
| 13 | **Carbendazim 25% + Flusilazole 12.5% SE** | Stem rot, Early leaf spot, **LATE leaf spot** | 640–800 ml | 259–324 ml | 500 L | 1.3–1.6 ml/L | **72 d** ⚠ |
| 14 | **Sulphur 80% WP** | Tikka leaf spot | 2.5–5.0 kg | 1.0–2.0 kg | 750–1000 L | ~5 g/L | ⚠ "-" |
| 15 | **Thiophanate methyl 41.7% SC** | Tikka leaf spot | 1000 ml | 405 ml | 500 L | 2 ml/L | 27 d |
| 16 | **Mancozeb 50% + Thiophanate methyl 25% WG** | Tikka leaf spot | 1500 g | 607 g | 500 L | 3 g/L | 24 d |
| 17 | **Metiram 70% WG** | Tikka | 2000 g | 810 g | 500–750 L | 2.7–4 g/L | 16 d |
| 18 | **Pydiflumetofen 6.89% + Difenoconazole 11.49% SC** | Tikka leaf spot, Rust | 300 ml | 121 ml | 500 L | 0.6 ml/L | 47 d |
| 19 | **Tebuconazole 10% + Sulphur 65% WG** | Tikka disease | 1250 g | 506 g | 500 L | 2.5 g/L | 31 d |

⚠ **Watch the long PHIs on groundnut.** Tebuconazole 25.9% EC = 49 days, and
Carbendazim+Flusilazole = 72 days. Late leaf spot peaks at 70–90 DAS in a 100–110 day
crop — a 72-day PHI product applied at the epidemic is a residue violation at harvest.
For a late-season spray use Chlorothalonil (14 d), Propiconazole (15 d),
Metiram (16 d) or Prochloraz+Propiconazole (19 d).

**Registered seed treatments (groundnut, for collar rot / dry root rot / early tikka):**
- **Mancozeb 75% WP — 25–30 g per 10 kg seed** as a water slurry (0.1 L water).
- **Carbendazim 12% + Mancozeb 63% WP — 2.5 g per kg seed.**
- **Carbendazim 25% + Mancozeb 50% WS — 30–35 g per 10 kg seed.**
- **Imidacloprid 18.5% + Hexaconazole 1.5% FS — 200 ml/100 kg seed** (collar rot, stem
  rot, tikka, rust + insect protection). Seed dresser; PHI not applicable.

---

## 9. MUSTARD

### 9.1 Mustard — APHID (*Lipaphis erysimi*)

**Only four products are registered for aphid on mustard as on 31.03.2026.** This is a
short list and it should be presented to the farmer as a short list.

| # | Product | Dose/ha | Dose/acre (derived) | Water/ha | Dilution | PHI |
|---|---|---|---|---|---|---|
| 1 | **Thiamethoxam 25% WG** | 50–100 g | 20–40 g | 500–1000 L | 0.05–0.2 g/L | **21 d** |
| 2 | **Dimethoate 30% EC** | 660 ml | 267 ml | 500–1000 L | 0.66–1.3 ml/L | ⚠ "-" not stated |
| 3 | **Oxydemeton-methyl 25% EC** | 1000 ml | 405 ml | 500–1000 L | 1–2 ml/L | ⚠ "-" not stated |
| 4 | **Chlorpyrifos 20% EC** | 500 ml | 202 ml | 500–1000 L | 0.5–1 ml/L | ⚠ "-" not stated |

Also registered on mustard but for **other** pests, not aphid:
Imidacloprid 70% WS @ 700 g/100 kg seed (mustard sawfly, painted bug);
Quinalphos 25% EC @ 1200 ml/ha (sawfly); Carbofuran 3% CG (leaf miner, whitefly).

**Thiamethoxam 25% WG** (neonicotinoid, IRAC 4A)
- ⚠ Trade names (not CIB&RC): Actara, Areva, Anant, Renova, Slogan.
- Registered: **Mustard — Aphid. 50–100 g formulation/ha (12.5–25 g a.i./ha)
  = 20–40 g/acre (derived), in 500–1000 L water/ha, PHI 21 days.**
- ⚠ Toxicity triangle: commonly **Blue** on Indian thiamethoxam 25% WG packs — verify.
- REI: not stipulated. Max applications: NOT FOUND on the label.
- **Incompatibility / BEES — this is the critical warning for mustard.** Mustard in flower
  is one of the most important bee forage crops in north India, and thiamethoxam is highly
  toxic to bees. **Spray only in the late evening after bee flight has ceased**, and if at
  all possible spray before full bloom or after peak bloom. Never spray a mustard field at
  midday during flowering. Inform neighbouring apiaries.

> ⚠ **NOT REGISTERED — Imidacloprid foliar spray on mustard.** Imidacloprid 17.8% SL is
> the most commonly recommended mustard aphid spray in Indian practice, but its only
> mustard registration is the **70% WS seed treatment for sawfly and painted bug**. There
> is no imidacloprid foliar-on-mustard-aphid entry in the CIB&RC list. Use thiamethoxam
> (registered) instead. ⚠
> **NOT REGISTERED — Acetamiprid on mustard.** Same situation.

---

## 10. CHICKPEA (Bengal gram)

### 10.1 Chickpea — WILT (*Fusarium oxysporum* f.sp. *ciceris*)

> **There is NO foliar fungicide registered — or effective — against chickpea wilt.**
> Fusarium wilt is a soil-borne vascular disease; once the plant wilts, nothing sprayed on
> the leaves will reverse it. Real management is:
> **(a) wilt-resistant varieties** — this is the primary control (e.g. JG 62-derived
> resistant lines, JG 315, JG 74, Avrodhi, WR 315, Vijay, Vishal — ⚠ variety choice is
> state-specific; refer the local SAU);
> **(b) seed treatment before sowing** (below);
> **(c) 3–4 year rotation** out of chickpea; **(d) deep summer ploughing**;
> **(e) sowing at the right time** — very early sowing in warm soil increases wilt.
> Advising a spray for chickpea wilt is a waste of the farmer's money.

**Registered SEED TREATMENTS for chickpea wilt / root rot:**

| Product | Registered target | Dose | Notes |
|---|---|---|---|
| **Tebuconazole 5.4% w/w FS** | Chickpea — **Root rot, Wilt** | **4.0 ml per 10 kg seed** (0.24 g a.i./10 kg) | Seed dresser; PHI not applicable |
| **Prochloraz 5.7% + Tebuconazole 1.4% w/w ES** | Chickpea — **Root rot (*Rhizoctonia solani*), Wilt (*Fusarium* spp.)** | **3.0 ml per 10 kg seed** | Seed dresser |
| **Tebuconazole 15% + Zineb 57% WDG** | Chickpea — **Wilt (*Fusarium oxysporum*), Root rot (*Rhizoctonia* spp.)** | **4.0 g per (10 kg) seed**; slurry "sufficient to coat the seeds uniformly" | Seed dresser; PHI NA |
| **Carbendazim 25% + Mancozeb 50% WS** | Bengal gram — Dry root rot, Collar rot | **30 g per 10 kg seed**, slurry 0.1 L | ⚠ registered for **dry root rot/collar rot**, NOT for Fusarium wilt |
| **Penflufen 13.28% + Trifloxystrobin 13.28% FS** | Bengal gram — Seed and seedling rot | 80–100 ml per (100 kg) seed | ⚠ seed/seedling rot only, not wilt |

⚠ **Bio-agent seed treatment** — *Trichoderma viride/harzianum* @ 4–10 g/kg seed is the
standard Indian recommendation for chickpea wilt and is covered by the separate CIB&RC
**Bio-Pesticides (Bio-fungicide)** list, not the chemical list used here:
https://ppqs.gov.in/sites/default/files/3._bio_pesticide_mup_biofungicide_as_on_31.03.2026.pdf
Exact registered rate: **NOT VERIFIED in this pass — requires verification.**
Note: **do not mix Trichoderma with a chemical fungicide seed treatment in the same
slurry** — the fungicide kills the bio-agent. If both are used, chemical first, dry,
then Trichoderma, or use Trichoderma alone.

### 10.2 Chickpea — POD BORER (*Helicoverpa armigera*)

**IPM first:** pheromone traps at 5/ha for monitoring (ETL = 8–10 moths/trap/night or
1–2 larvae/metre row), bird perches at 50/ha, and **HaNPV @ 250 LE/ha** — these are
genuinely effective on chickpea and reduce spray count materially.

| # | Product | Registered crop wording | Dose/ha | Dose/acre (derived) | Water/ha | Dilution | PHI |
|---|---|---|---|---|---|---|---|
| 1 | **Flubendiamide 39.35% SC** | Bengal gram | 100 ml | 40 ml | 500 L | 0.2 ml/L | **5 d** |
| 2 | **Flubendiamide 20% WG** | Bengal gram | 250 g | 101 g | 500 L | 0.5 g/L | 15 d |
| 3 | **Chlorantraniliprole 18.5% SC** | Bengal gram | 125 ml | 50 ml | 500 L | 0.25 ml/L | 11 d |
| 4 | **Chlorantraniliprole 47.85% SC** | Chickpea | 41.66 ml | 17 ml | 500 L | 0.08 ml/L | 26 d |
| 5 | **Emamectin benzoate 5% SG** | Chickpea | 220 g | 89 g | 500 L | 0.44 g/L | 14 d |
| 6 | **Emamectin benzoate 1.9% EC** | Chickpea | 375 ml | 152 ml | 500 L | 0.75 ml/L | 14 d |
| 7 | **Indoxacarb 14.5% SC** | Chickpea | 400–500 ml | 162–202 ml | 500 L | 0.8–1 ml/L | 19 d |
| 8 | **Indoxacarb 15.8% EC** | Chickpea | 333 ml | 135 ml | 500 L | 0.67 ml/L | 18 d |
| 9 | **Spinetoram 11.7% SC** | Chickpea | 375–450 ml | 152–182 ml | 500–1000 L | 0.4–0.9 ml/L | 20 d |
| 10 | **Novaluron 10% EC** | Bengal gram | 750 ml | 304 ml | 500 L | 1.5 ml/L | **7 d** |
| 11 | **Lambda-cyhalothrin 5% EC** | Chickpea | 500 ml | 202 ml | 300–400 L | 1.25–1.7 ml/L | 6 d |
| 12 | **Quinalphos 25% EC** | Bengal gram | 1000 ml | 405 ml | 500–1000 L | 1–2 ml/L | ⚠ "-" |
| 13 | **Chlorpyrifos 1.5% DP** | Bengal gram | 25 kg (dust) | 10.1 kg | — dust | — | 7 d |
| 14 | **Flubendiamide 8.33% + Deltamethrin 5.56% SC** | Chickpea | 250 ml | 101 ml | 500 L | 0.5 ml/L | **7 d** |
| 15 | **Chlorantraniliprole 5.2% + Novaluron 8.5% SC** | Chickpea | 400 ml | 162 ml | 500 L | 0.8 ml/L | **7 d** |
| 16 | **Novaluron 5.25% + Emamectin benzoate 0.9% SC** | Chickpea | 875 ml | 354 ml | 500 L | 1.75 ml/L | 11 d |
| 17 | **Novaluron 5.25% + Indoxacarb 4.5% SC** | Chickpea | 825–875 ml | 334–354 ml | 500 L | 1.65–1.75 ml/L | **9 d** |
| 18 | **Chlorantraniliprole 15% + Emamectin benzoate 7.5% SC** | Bengal gram | 200 ml | 81 ml | 500 L | 0.4 ml/L | 19 d |
| 19 | **Indoxacarb 16% + Chlorantraniliprole 12% OD** | Chickpea | 400 ml | 162 ml | 500 L | 0.8 ml/L | 26 d |
| 20 | **Methoxyfenozide 5% + Chlorpyriphos 25% SE** | Bengal gram | 2000 ml | 810 g | 500 L | 4 ml/L | 15 d |

⚠ **Do not confuse Chlorantraniliprole 18.5% SC (125 ml/ha) with Chlorantraniliprole
47.85% SC (41.66 ml/ha).** Same molecule, 2.6× different concentration. Dosing the
47.85% product at the 18.5% rate is a 3× overdose. **The advisory device must always
carry the % with the molecule name.**

---

# MEDIUM PRIORITY CROPS

## 11. MANGO

### 11.1 Mango — HOPPER (*Idioscopus* / *Amritodus* spp.)

Mango is a tree crop: CIB&RC gives most doses **per 100 L of water or per tree**, with
spray volume "as required depending on size of tree". Per-hectare figures assume ~1000 L
of spray fluid per hectare for a bearing orchard.

| # | Product | Dose | Water | PHI |
|---|---|---|---|---|
| 1 | **Thiamethoxam 25% WG** | 100 g/ha (25 g a.i./ha) = 40 g/acre derived | 1000 L/ha | 30 d |
| 2 | **Imidacloprid 17.8% SL** | **2–4 ml per tree** in **10 L water per tree** (0.4–0.8 g a.i./tree) | 10 L/tree | 45 d |
| 3 | **Lambda-cyhalothrin 5% EC** | **0.5–1.0 ml per litre of water** (0.0025–0.005%) | as required | 7 d |
| 4 | **Lambda-cyhalothrin 24% WDG** | 300 g/ha (72 g a.i./ha) = 121 g/acre derived | 1500 L/ha | 7 d |
| 5 | **Deltamethrin 2.8% EC** | **0.33–0.5 ml per litre** (0.03–0.05%) | as required | **1 d** |
| 6 | **Flonicamid 50% WG** | 400 g/ha (200 g a.i.) = 162 g/acre derived | 1000 L/ha | 15 d |
| 7 | **Tolfenpyrad 15% EC** | 1000 ml/ha = 405 ml/acre derived | 500 L/ha | 7 d |
| 8 | **Pymetrozine 50% WG** | 300 g/ha = 121 g/acre derived | 1000 L/ha | 36 d |
| 9 | **Triflumezopyrim 10% SC** | **23.6 ml per 100 L water** | 1000 L/ha | 30 d |
| 10 | **Oxydemeton-methyl 25% EC** | 1500–2000 ml/ha | 1500–2000 L/ha | ⚠ "-" |

**Timing is everything for mango hopper.** Two sprays: **(1) at panicle emergence**,
**(2) at pea-sized fruit**. **Never spray during full bloom** — it kills the pollinators
the crop depends on and causes fruit drop. Alternate the chemistry between the two
sprays; hopper resistance to imidacloprid is established in Indian orchards.

### 11.2 Mango — ANTHRACNOSE (*Colletotrichum gloeosporioides*)

| # | Product | Dose | Water | PHI |
|---|---|---|---|---|
| 1 | **Copper oxychloride 50% WG** | **0.24% = 240 g/100 L water** | as required | 10 d |
| 2 | **Azoxystrobin 23% SC** | **0.1% = 100 ml/100 L water** | as required, by tree size | **5 d** |
| 3 | **Metiram 70% WG** | **100–125 g/100 L water**; ≈125 g/ha at 1000 L | 1000 L/ha | 64 d ⚠ |
| 4 | **Carbendazim 12% + Mancozeb 63% WP** | **0.15% = 1.5 g/L water** | as required | **7 d** |
| 5 | **Tebuconazole 38.39% SC** | **110 ml/100 L water** | as required | 15 d |
| 6 | **Propiconazole 13.9% + Difenoconazole 13.9% EC** | 1000 ml/ha = 405 ml/acre derived | 500 L/ha | 10 d |
| 7 | **Tebuconazole 50% + Trifloxystrobin 25% WG** | **0.075–0.1% = 75–100 g/100 L water** | as required | 15 d |
| 8 | **Fluopyram 17.7% + Tebuconazole 17.7% SC** | 625–750 ml/ha (also post-harvest anthracnose/soft rot) | 750–1000 L/ha | 20 d |
| 9 | **Fludioxonil 20.4% SC** | **150 ml/100 L water** (*Colletotrichum*, *Botryosphaeria*, *Diplodia*) | 100 L | 30 d |

### 11.3 Mango — POWDERY MILDEW (*Oidium mangiferae*)

| # | Product | Dose | Water | PHI |
|---|---|---|---|---|
| 1 | **Sulphur 80% WP** | 3.13 kg/ha = 1.27 kg/acre derived | 750–1000 L/ha | ⚠ "-" |
| 2 | **Sulphur 80% WG** | 1.875–2.50 kg/ha | 750–1000 L/ha | ⚠ "-" |
| 3 | **Sulphur 55.16% SC** | **0.30% = 300 ml/100 L water** | as required | 10 d |
| 4 | **Hexaconazole 5% EC** | **0.1% = 100 ml/100 L water** | as required | 30 d |
| 5 | **Hexaconazole 5% SC** | **0.2% = 200 ml/100 L water** | as required | 27 d |
| 6 | **Carbendazim 46.27% SC** | **0.1% = 100 ml/100 L water** | as required | 15 d |
| 7 | **Penconazole 10% EC** | **50 ml/100 L water**; **10 L water per tree** | 10 L/tree | 30 d |
| 8 | **Dinocap 48% EC** | 5 g/… ⚠ row garbled in source | 10 L | ⚠ "-" — **verify on pack** |
| 9 | **Meptyl dinocap 35.7% EC** | 308.6–342.8 ml/ha = 125–139 ml/acre derived | 1000 L/ha | **7 d** |
| 10 | **Metrafenone 500 g/L SC** | **0.2 ml/L water** (≈200 ml/ha at 1000 L) | 1000 L/ha | 35 d |
| 11 | **Tetraconazole 3.8% EW** | 1250 ml/ha = 506 ml/acre derived | 1000 L/ha | 24 d |
| 12 | **Fluxapyroxad 250 + Pyraclostrobin 250 g/L SC** | 150–200 ml/ha | 1000 L/ha | 38 d |
| 13 | **Azoxystrobin 23% SC** | **0.1% = 100 ml/100 L** (mildew + anthracnose) | as required | **5 d** |

⚠ **Sulphur phytotoxicity:** do not apply sulphur above ~32–35 °C, and never within
**3–4 weeks** of an oil spray. Do not tank-mix sulphur with dinocap/meptyldinocap.

---

## 12. GRAPE

### 12.1 Grape — DOWNY MILDEW (*Plasmopara viticola*)

⚠ **Grape is India's most residue-scrutinised crop** (EU export MRLs). The Maharashtra
State Grape Growers Association / NRC Grapes **residue-compliant spray calendar** with
per-stage PHI restrictions is the operative document for export vineyards — this CIB&RC
list is the legal minimum, not the export standard. **Flag this to any grape grower.**

| # | Product | Dose/ha | Dose/acre (derived) | Water/ha | Dilution | PHI |
|---|---|---|---|---|---|---|
| 1 | **Mancozeb 75% WP** | 1.5–2.0 kg | 600–800 g | 750 L | 2–2.7 g/L | ⚠ "-" |
| 2 | **Copper oxychloride 50% WP** | 2.5 kg | 1.0 kg | 750–1000 L | 2.5–3.3 g/L | ⚠ "-" |
| 3 | **Copper hydroxide 61.41% WG** | 1250 g | 506 g | 500–1000 L | 1.25–2.5 g/L | **3 d** |
| 4 | **Copper hydroxide 53.8% DF** | 1500 g | 607 g | 1000 L | 1.5 g/L | 12 d |
| 5 | **Dimethomorph 50% WP** | 1000 g | 405 g | 750 L | 1.33 g/L | 25 d |
| 6 | **Cyazofamid 34.5% SC** | 200 ml | 81 ml | 500 L | 0.4 ml/L | **7 d** |
| 7 | **Mandipropamid 23.4% SC** | — | — | 500–1000 L | **0.8 ml/L (label)** | **5 d** |
| 8 | **Azoxystrobin 23% SC** | 500 ml | 202 ml | 500–750 L | 0.67–1 ml/L | **7 d** |
| 9 | **Kresoxim-methyl 44.3% SC** | 600–700 ml | 243–283 ml | 500 L | 1.2–1.4 ml/L | **7 d** |
| 10 | **Picoxystrobin 22.52% SC** | 400 ml | 162 ml | 750–1000 L | 0.4–0.53 ml/L | **7 d** |
| 11 | **Amisulbrom 20% SC** | 375 ml | 152 ml | 400–1000 L | 0.4–0.9 ml/L | 59 d ⚠ |
| 12 | **Ethaboxam 40% SC** | 500–663 ml | 202–268 ml | 1000 L | 0.5–0.66 ml/L | 55 d ⚠ |
| 13 | **Picarbutrazox 9.53% SC** | 1000–1250 ml | 405–506 ml | 500 L | 2–2.5 ml/L | 60 d ⚠ |
| 14 | **Propineb 70% WP** | **0.30% = 300 g/100 L** | — | as required | 3 g/L | 40 d |
| 15 | **Captan 75% WP** | 1667 g | 675 g | 1000 L | 1.67 g/L | 8 d |
| 16 | **Chlorothalonil 75% WP** | **0.2% = 200 g/100 L** | — | 100 L | 2 g/L | 60 d ⚠ |
| 17 | **Copper sulphate pentahydrate 6% SC** | **2.5 ml/L** | — | 500–1000 L | 2.5 ml/L | 45 d |

### 12.2 Grape — POWDERY MILDEW (*Erysiphe/Uncinula necator*)

| # | Product | Dose/ha | Dose/acre (derived) | Water/ha | Dilution | PHI |
|---|---|---|---|---|---|---|
| 1 | **Sulphur 80% WP** | 2.5–5.0 kg | 1.0–2.0 kg | 750–1000 L | ~5 g/L | ⚠ "-" |
| 2 | **Sulphur 80% WG** | 1.875–2.50 kg | 759 g–1.0 kg | 750–1000 L | ~2.5 g/L | ⚠ "-" |
| 3 | **Sulphur 40% SC** | 3.00 kg | 1.21 kg | 1000 L | 3 ml/L | ⚠ "-" |
| 4 | **Hexaconazole 5% EC** | 500–1000 ml | 202–405 ml | 500 L | 1–2 ml/L | 14 d |
| 5 | **Hexaconazole 2% SC** | 1.5–3.0 L | 607 ml–1.21 L | 500–750 L | 2–6 ml/L | 14 d |
| 6 | **Myclobutanil 10% WP** | **0.04% = 400 g/ha** | 162 g | 500 L | 0.4 g/L | 15 d |
| 7 | **Penconazole 10% EC** | **50 ml/100 L water** | — | as required | 0.5 ml/L | 30 d |
| 8 | **Bupirimate 26.7% EC** | 3000 ml | 1.21 L | 1000 L | 3 ml/L | 15 d |
| 9 | **Metrafenone 500 g/L SC** | 250 ml | 101 ml | 750 L | 0.33 ml/L | 22 d |
| 10 | **Pyriofenone 18% SC** | 600 ml | 243 ml | 750 L | 0.8 ml/L | **5–7 d** ⚠ (two rows: 5 and 7) |
| 11 | **Cyflufenamid 5% EW** | 500 ml | 202 ml | 400–1000 L | 0.5–1.25 ml/L | 25 d |
| 12 | **Polyoxin D Zinc salt 5% SC** | 600 g | 243 g | 500–1000 L | 0.6–1.2 g/L | **0 d** |
| 13 | **Meptyl dinocap 35.7% EC** | 308.6–342.8 ml | 125–139 ml | 750–1000 L | 0.35 ml/L | 30 d |
| 14 | **Tetraconazole 3.8% EW** | 625–750 ml | 253–304 ml | 500–1000 L | 0.7–1.25 ml/L | 30 d |
| 15 | **Thiophanate methyl 70% WP** | 715 g | 289 g | 750–1000 L | ~0.8 g/L | **7 d** |
| 16 | **Difenoconazole 25% EC** | **0.03% = 30 ml/100 L** (anthracnose + PM) | — | 500 L | 0.3 ml/L | 10 d |
| 17 | **Azoxystrobin 23% SC** | 500 ml | 202 ml | 500–750 L | 0.67–1 ml/L | **7 d** |
| 18 | **Tebuconazole 38.39% SC** | 500–550 ml | 202–223 ml | 375–500 L | ~1 ml/L | 60 d ⚠ |
| 19 | **Lime sulphur 22% SC** | 2–5 L/ha (dormant/February + 2 summer dustings) | 810 ml–2.0 L | — | — | — |

⚠ **Source disagreement flagged:** Pyriofenone 18% w/v SC appears **twice** in the CIB&RC
fungicide list for grape powdery mildew at the same dose (600 ml/ha) but with **PHI 7 days
(p.26) and PHI 5 days (p.34)**. Advise the longer figure, **7 days**.

⚠ **Sulphur + lime sulphur + oils:** keep a minimum 3–4 week gap between sulphur/lime
sulphur and any oil spray on grape. Do not apply sulphur above 32 °C.

---

## 13. BANANA — SIGATOKA LEAF SPOT (*Mycosphaerella musicola* / *M. fijiensis*)

| # | Product | Dose/ha | Dose/acre (derived) | Water/ha | Dilution | PHI |
|---|---|---|---|---|---|---|
| 1 | **Mancozeb 75% WP** | 1.5–2.0 kg | 600–800 g | 750 L | 2–2.7 g/L | ⚠ "-" |
| 2 | **Pyraclostrobin 20% WG** | 750 g | 304 g | 500 L | 1.5 g/L | **103 d** ⚠ |
| 3 | **Azoxystrobin 18.2% + Cyproconazole 7.3% SC** | **1% = 10 ml/L** | — | 500 L | 10 ml/L ⚠ | 10 d |
| 4 | **Azoxystrobin 18.2% + Difenoconazole 11.4% SC** | 1000 ml | 405 ml | 500 L | 2 ml/L | 57 d |
| 5 | **Propiconazole 13.9% + Difenoconazole 13.9% EC** | 350 ml | 142 ml | 500 L | 0.7 ml/L | 35 d |
| 6 | **Tebuconazole 50% + Trifloxystrobin 25% WG** | 350 g | 142 g | 700 L | 0.5 g/L | 20 d |
| 7 | **Fluxapyroxad 167 + Pyraclostrobin 333 g/L SC** | 300 ml | 121 ml | 500 L | 0.6 ml/L | 10 d |
| 8 | **Metiram 55% + Pyraclostrobin 5% WG** | 1500–1750 g | 607–708 g | 500 L | 3–3.5 g/L | 85 d ⚠ |
| 9 | **Pyraclostrobin 133 + Epoxiconazole 50 g/L SE** | 750 ml | 304 ml | 500 L | 1.5 ml/L | 24 d |
| 10 | **Copper oxychloride 50% WP** | 2.5 kg (registered as "leaf spot") | 1.0 kg | 750–1000 L | 2.5–3.3 g/L | ⚠ "-" |

⚠ **The 10 ml/L figure for Azoxystrobin+Cyproconazole SC on banana (row 3) is printed in
the source as "1 %".** That is an unusually high in-tank concentration for a strobilurin
SC and is inconsistent with the same product's other crop entries. **NOT RELIABLE —
requires verification against the container label before use.**

**Non-chemical control that actually carries the load on Sigatoka:** remove and destroy
infected lower leaves at every de-suckering round; improve drainage; maintain plant
spacing for airflow; **add a spreader/sticker + 1% mineral oil** to fungicide sprays
(standard banana practice — the oil is a carrier, not a registered pesticide rate).
Rotate FRAC groups strictly — Sigatoka develops strobilurin resistance very fast.

---

## 14. CITRUS — CANKER (*Xanthomonas citri* subsp. *citri*)

> **Citrus canker is a BACTERIAL disease. No chemical cures it.** Copper and antibiotics
> only **suppress** new infection by protecting fresh flush and young fruit; they cannot
> eradicate the bacterium from an infected tree. The essential controls are:
> canker-free nursery planting material; **pruning out and burning cankered twigs in the
> dry season**; **windbreaks** (wind-driven rain spreads it); **leaf miner control** —
> citrus leaf miner tunnels are the main entry wound, so controlling leaf miner is one of
> the most effective anti-canker measures available; disinfecting pruning tools; and not
> working the orchard when foliage is wet.

**Registered for citrus canker (suppression only):**

| Product | Dose | Water | PHI |
|---|---|---|---|
| **Copper oxychloride 50% WP** | 2.5 kg/ha (1.0 kg/acre derived) | 750–1000 L/ha | ⚠ "-" |
| **Copper sulphate 47.15% + Mancozeb 30% WDG** | 2500 g/ha (1.0 kg/acre derived); registered "**Bacterial canker** and Alternaria spot" | 500 L/ha → 5 g/L | 10 d |
| **Streptomycin sulphate 90% + Tetracycline hydrochloride 10% SP** ("Streptocycline") | **Spray 50–100 ppm solution, repeated at 15–20 day intervals after the appearance of new growth. Cover foliage and young fruit fully.** | — | ⚠ "-" |
| **Streptomycin sulphate 9% + Tetracycline hydrochloride 1% SP** | Same 50–100 ppm instruction | — | ⚠ "-" |

⚠ **Streptocycline ppm arithmetic — get this right or the spray is useless or illegal.**
For the **9% + 1% SP** product (10% total antibiotic), 100 ppm means **1 g of product per
litre of water**. For the **90% + 10% SP** product (100% antibiotic), 100 ppm means
**0.1 g per litre** — i.e. **1 g in 10 litres**. Confusing the two is a 10× error.
**The CIB&RC table gives no per-hectare dose and no waiting period for streptocycline on
citrus — PHI NOT FOUND, requires verification.**
⚠ Antibiotic use in agriculture is under active regulatory review in India on
antimicrobial-resistance grounds. Prefer copper + sanitation; use streptocycline sparingly
and never as a routine calendar spray.

---

## 15. POMEGRANATE — BACTERIAL BLIGHT / OILY SPOT (*Xanthomonas axonopodis* pv. *punicae*)

> **Also bacterial — no cure.** "Telya" is managed by an integrated programme, not a
> spray: disease-free planting material; a **deliberate bahar (rest) treatment** with
> defoliation and removal/burning of all infected plant parts during the rest period;
> pruning out infected twigs 15 cm below the lesion; avoiding overhead irrigation;
> orchard sanitation; and restricting movement of workers/tools between infected and clean
> blocks. Chemical sprays only slow spread on protected new growth.

**Registered on pomegranate for bacterial blight:**

| Product | Registered target | Dose | Water | PHI |
|---|---|---|---|---|
| **Copper sulphate pentahydrate 6% SC** | Pomegranate — **Bacterial blight** | **2.5 ml per litre** (0.15 g a.i./L) | 750–1000 L/ha | 33 d |
| **Copper sulphate 47.15% + Mancozeb 30% WDG** | Pomegranate — **Bacterial blight**, Alternaria & Cercospora leaf spot | 2500 g/ha = 1.0 kg/acre (derived) | 500 L/ha → 5 g/L | 44 d |
| **Kasugamycin 5% + Copper oxychloride 45% WP** | Pomegranate — **Bacterial blight**, leaf spot, fruit rot, anthracnose | **0.1% = 1 g per litre** (0.05% a.i.) | 500–1000 L/ha | 10 d |

⚠ **Streptocycline is NOT REGISTERED on pomegranate** in the CIB&RC list (its bactericide
registrations here are on citrus and rice). Streptocycline + COC sprays for telya are
extremely common in Maharashtra pomegranate and are **off-label**. The registered
antibiotic-containing option for pomegranate is **Kasugamycin 5% + COC 45% WP**.

---

## 16. TURMERIC / GINGER — RHIZOME ROT (*Pythium* spp.)

**Turmeric — Rhizome rot (plus leaf blotch and leaf spot):**
- **Azoxystrobin 18.2% + Difenoconazole 11.4% w/w SC**
- Dose: **0.1% = 1 ml per litre of water** (a.i. 0.3 g/L). Spray volume **500 L/ha**
  → **≈500 ml/ha = 202 ml/acre (derived).** **PHI 60 days.**
- Source: CIB&RC MUP Fungicides 31.03.2026, p.45.

**Ginger — Rhizome rot (soil drench):**
- **Metalaxyl-M 3.3% + Chlorothalonil 33.1% SC**
- Dose: **200 ml per 100 L of water, or 2000 ml/ha** (72.8 g a.i./100 L).
  Applied as **soil drench**, drench volume **1000 L/ha**. **PHI 193 days.**
  Per acre (derived): **810 ml in ~400 L of drench.**
- Source: CIB&RC MUP Fungicides 31.03.2026, p.68.

⚠ **This is a short list, and the omissions matter.** The near-universal Indian
recommendations for rhizome rot — **Mancozeb 0.3% drench**, **Metalaxyl-MZ 0.125% drench**,
**Trichoderma + neem cake in the bed**, and **rhizome seed treatment in mancozeb/carbendazim
for 30 minutes before storage/sowing** — do **not** appear as turmeric or ginger entries in
the CIB&RC chemical list as on 31.03.2026. Treat all of those as **NOT REGISTERED on
turmeric/ginger** and say so.

**What actually controls rhizome rot** and carries no registration problem:
**raised beds with sharp drainage** (the disease is a waterlogging disease above all),
disease-free seed rhizomes from a healthy field, solarised nursery beds, removing and
destroying infected clumps **with the surrounding soil**, and a 2–3 year rotation.

---

## 17. WHEAT — LOOSE SMUT (*Ustilago segetum* var. *tritici*) — SEED TREATMENT

> **Loose smut is seed-borne and internal to the embryo.** It cannot be sprayed. It is
> controlled **only** by seed treatment before sowing (or by using certified clean seed).
> A systemic seed dressing is the entire control programme.

| # | Product | Registered dose | Slurry water | Notes |
|---|---|---|---|---|
| 1 | **Carboxin 75% WP** | **2.0–2.5 g per kg seed** (1.5–1.875 g a.i./kg) | N/A dry/slurry | "Only one-time seed treatment required". Also covers **flag smut** and **bunt**. |
| 2 | **Carboxin 37.5% + Thiram 37.5% WS** ("Vitavax Power" ⚠ trade) | **3.0 g per kg seed** (2.25 g a.i./kg) | **10 ml/kg seed** to make slurry | Covers loose smut + other seed-borne and early soil-borne diseases. Waiting period not applicable. |
| 3 | **Carboxin 17.5% + Thiram 17.5% FF** | **25–30 g per 10 kg seed** | 100 ml | Flowable seed dressing |
| 4 | **Carbendazim 50% WP** | **2 g per kg seed** (1 g a.i./kg) | **1 L per 10 kg seed** (wet slurry treatment) | Wet slurry method |
| 5 | **Tebuconazole 5.4% w/w FS** | **3.0 ml per 10 kg seed** (0.18 g a.i./10 kg) | — | Loose smut **and** flag smut |
| 6 | **Tebuconazole 5.36% FS** | **3.33 ml per 10 kg seed** | — | Loose smut |
| 7 | **Tebuconazole 2% DS** | **0.2 kg per 10 kg seed** ⚠ — **implausible (2% of seed weight); source row garbled. NOT RELIABLE — verify on pack.** | 10 L/10 kg ⚠ | ⚠ |
| 8 | **Difenoconazole 3% WS** | **200 g per (100 kg) seed** (6.0 g a.i.) | seed dresser | Loose smut |
| 9 | **Carbendazim 25% + Mancozeb 50% WS** | **30–35 g per 10 kg seed** | 0.1 L | Loose smut |
| 10 | **Triticonazole 80 + Pyraclostrobin 40 g/L FS** | **1.0 ml per (kg) seed** | "sufficient to coat seeds uniformly" | PHI NA |
| 11 | **Azoxystrobin 1.3% + Tebuconazole 0.22% + Thiamethoxam 25.9% FS** | **60 ml per (100 kg) seed** | — | Loose smut + **termite** + aphid |
| 12 | **Sedaxane 2.2% + Fludioxonil 2.2% + Thiamethoxam 22.8% FS** | **1.0–2.0 ml per kg seed**; slurry **10–15 ml/kg** | — | Loose smut, karnal bunt, aphids, termites |

**Carboxin 37.5% + Thiram 37.5% WS** — the workhorse
- ⚠ Trade names (not CIB&RC): Vitavax Power, Vitavax 200.
- **3 g per kg seed = 300 g per 100 kg (one quintal) of wheat seed**, made into a slurry
  with **10 ml water per kg seed (1 litre per 100 kg)**.
- ⚠ Toxicity triangle: usually **Blue** — verify on pack.
- PHI: not applicable (seed treatment at sowing). REI: not applicable.
- **Treat seed in shade, dry it in shade, and sow within a few days.** Do not feed treated
  seed to humans or livestock, ever — this is the single most common fatal pesticide
  accident pattern with treated seed in India. Keep treated seed in clearly marked bags.
- ⚠ **Do not mix chemical seed dressing with Rhizobium/PSB or Trichoderma in the same
  slurry.** If both are needed: fungicide first, dry fully, biofertiliser last, immediately
  before sowing.

The traditional **solar heat treatment** (soak seed in water 4 h in the morning, then dry
in hot summer sun on a floor for the rest of the day) also controls loose smut and costs
nothing — worth surfacing for organic/low-input growers.

---

## 18. RICE — BACTERIAL LEAF BLIGHT (*Xanthomonas oryzae* pv. *oryzae*)

> **Bacterial — no chemical cures it.** BLB explodes after heavy wind-driven rain, in
> fields with **excess nitrogen** and **standing deep water**. The three things that
> actually reduce loss:
> **(1) STOP or reduce top-dressed nitrogen the moment BLB appears** — this is the single
> most effective intervention and it is free;
> **(2) drain the field** and alternate wet/dry rather than keeping deep standing water;
> **(3) resistant varieties** carrying *Xa* genes (⚠ variety choice is state-specific —
> refer the local SAU).
> Copper sprays and streptocycline only suppress spread onto new tissue.

**Registered on rice for bacterial leaf blight:**

| Product | Registered target | Dose/ha | Dose/acre (derived) | Water/ha | Dilution | PHI |
|---|---|---|---|---|---|---|
| **Copper hydroxide 53.8% DF** | Rice — **False smut, Bacterial leaf blight** | 1500 g | 607 g | 500 L | 3 g/L | 10 d |
| **Copper sulphate pentahydrate 6% SC** | Rice — **Bacterial leaf blight** | 1000 ml | 405 ml | 500 L (or **20 L/ha by drone**) | 2 ml/L | 21 d |
| **Tribasic copper sulfate 34.5% SC** | Rice — **False smut & Bacterial leaf blight** | 2000 ml | 810 ml | 500 L | 4 ml/L | 32 d |
| **Kasugamycin 1% + Tebuconazole 14% + Kresoxim-methyl 20% SC** | Rice — Leaf & panicle blast, sheath blight, **Bacterial leaf blight**, grain discolouration | 1000–1250 ml | 405–506 ml | 500 L | 2–2.5 ml/L | 30 d |
| **Streptomycin sulphate 90% + Tetracycline HCl 10% SP** ("Streptocycline") | Paddy — **Bacterial leaf blight** | **Seed treatment:** soak seed in **40 ppm** solution for 12 h before sowing. **Seedling dip:** 40–100 ppm. **Spray: 100–150 ppm at early tillering; a second spray if necessary before grain set.** | — | — | — | ⚠ "-" |
| **Streptomycin sulphate 9% + Tetracycline HCl 1% SP** | Paddy — Bacterial leaf blight | Same ppm instructions | — | — | — | ⚠ "-" |

⚠ Same **ppm arithmetic warning** as citrus: 100 ppm = **1 g/L** of the 9%+1% product,
but **0.1 g/L** of the 90%+10% product. And the CIB&RC table gives **no waiting period**
for streptocycline on paddy — **PHI NOT FOUND, requires verification.**

⚠ Note the drone entry: Copper sulphate pentahydrate 6% SC carries a registered
**drone spray volume of 20 L/ha** alongside the 500 L/ha knapsack volume — one of the few
CIB&RC entries with an explicit UAV rate.

---

## 19. GREEN GRAM & SOYBEAN — WHITEFLY (vector of Yellow Mosaic Virus)

> **Yellow Mosaic Virus (MYMV/MYMIV) cannot be cured or sprayed.** Once a plant shows
> yellow mosaic it stays infected and should be **rogued out and destroyed**. The only
> chemical lever is **killing the whitefly vector early**, before it moves the virus —
> which means the **first 30–40 days after sowing** matter far more than any later spray.
> Resistant/tolerant varieties + early sowing + roguing + border crops of maize/sorghum
> are the real programme.

### 19.1 Green gram (moong) — Whitefly

**Only ONE product is registered for whitefly on green gram as on 31.03.2026:**

**Pyriproxyfen 10% + Bifenthrin 10% w/w EC**
- Registered crop/target: **Green gram — Whitefly.**
- **Dose: 1000 ml formulation/ha (100 + 100 g a.i./ha) = 405 ml/acre (derived).**
- Spray volume **500 L/ha** (200 L/acre) → **2 ml per litre.**
- **PHI 25 days.**
- ⚠ Toxicity triangle: bifenthrin-containing EC — commonly **Yellow**; verify on pack.
- Source: CIB&RC MUP Insecticides 31.03.2026, p.86.

> **NOT FOUND — requires verification:** there is **no** registered
> **thiamethoxam, imidacloprid, acetamiprid, diafenthiuron, spiromesifen or triazophos
> whitefly use on green gram** in the CIB&RC list. All of these are routinely recommended
> and sprayed on moong for YMV vector control in India. **They are off-label on green
> gram.** This is a significant, real gap in Indian registration — say so plainly rather
> than substituting a dose from another pulse.

### 19.2 Soybean — Whitefly

| Product | Registered target | Dose/ha | Dose/acre (derived) | Water/ha | Dilution | PHI |
|---|---|---|---|---|---|---|
| **Flonicamid 50% WG** | Aphids, Jassids, **Whitefly** | 200 g | 81 g | 500 L | 0.4 g/L | 35 d |
| **Acetamiprid 25% + Bifenthrin 25% WG** | **Whitefly**, girdle beetle, semilooper, tobacco caterpillar | 250 g | 101 g | 500 L | 0.5 g/L | 28 d |
| **Bifenthrin 32% + Chlorantraniliprole 12% WG** | **Whitefly**, girdle beetle, green semilooper, stem fly | 250 g | 101 g | 500 L | 0.5 g/L | 40 d |
| **Pyriproxyfen 10% + Bifenthrin 10% EC** | **Whitefly** | 1000 ml | 405 ml | 500 L | 2 ml/L | 35 d |
| **Thiamethoxam 30% FS** (seed treatment) | Stem fly, girdle beetle, **whitefly** | **6 ml per kg seed** (1.8 g a.i./kg) | — | 6–8 ml/kg slurry | NA |
| **Thiamethoxam 30% WS** (seed treatment) | Stem fly, girdle beetle, **whitefly** | **6 ml per kg seed** | — | 6–8 ml/kg | NA |

**The soybean seed treatment is the high-value recommendation here** — Thiamethoxam 30%
FS/WS at 6 ml/kg seed protects through the critical early-vector window when YMV spread
actually happens, at a fraction of the cost and risk of repeated foliar sprays.

---

# APPENDIX A — EVERY "NOT FOUND" AND "NOT REGISTERED" FINDING IN ONE PLACE

These are the answers the device must **refuse** to give a dose for. Each one is a case
where common Indian field practice is not backed by a CIB&RC registration for that crop.

| # | Crop | Product / practice | Status |
|---|---|---|---|
| 1 | Potato | **Difenoconazole 25% EC** for early blight | **NOT REGISTERED on potato** |
| 2 | Onion | **Straight Mancozeb 75% WP/WG** for purple blotch | **NOT REGISTERED on onion** (only inside combinations) |
| 3 | Onion | **Spinosad / Spinetoram** for thrips | **NOT REGISTERED on onion** |
| 4 | Onion | **Fipronil 5% SC** for thrips (the 80% WG *is* registered) | **NOT REGISTERED on onion** |
| 5 | Sugarcane | **Carbendazim 0.1% sett dip** for red rot | **NOT REGISTERED on sugarcane** |
| 6 | Sugarcane | Fipronil 0.3% GR waiting period printed as "09" days | **NOT RELIABLE — source error suspected; verify** |
| 7 | Mustard | **Imidacloprid foliar spray** for aphid | **NOT REGISTERED** (only 70% WS seed treatment, for sawfly/painted bug) |
| 8 | Mustard | **Acetamiprid** for aphid | **NOT REGISTERED on mustard** |
| 9 | Chickpea | Any **foliar fungicide** for Fusarium wilt | **Does not exist — no cure; seed treatment + resistant variety only** |
| 10 | Chickpea | *Trichoderma* seed-treatment rate | **NOT VERIFIED — in the bio-pesticide list, not checked this pass** |
| 11 | Pomegranate | **Streptocycline** for bacterial blight | **NOT REGISTERED on pomegranate** (registered on citrus and rice only) |
| 12 | Citrus | Streptocycline **PHI / per-ha dose** for canker | **NOT FOUND — requires verification** |
| 13 | Rice | Streptocycline **PHI** for BLB | **NOT FOUND — requires verification** |
| 14 | Turmeric / Ginger | **Mancozeb drench, Metalaxyl-MZ drench, carbendazim rhizome dip** | **NOT REGISTERED on turmeric/ginger** |
| 15 | Green gram | **Thiamethoxam / Imidacloprid / Acetamiprid / Diafenthiuron / Spiromesifen** for whitefly | **NOT REGISTERED on green gram** — only Pyriproxyfen+Bifenthrin |
| 16 | Banana | Azoxystrobin 18.2% + Cyproconazole 7.3% SC printed at "1 %" (10 ml/L) | **NOT RELIABLE — implausible; verify on pack** |
| 17 | Wheat | Tebuconazole 2% DS printed at 0.2 kg per 10 kg seed | **NOT RELIABLE — implausible; verify on pack** |
| 18 | Mango | Dinocap 48% EC row (2.4 g a.i. / 5 g / 10 L) | **Garbled in source — verify on pack** |
| 19 | Cotton | **Flupyradifurone 17.09% SL** for jassid/whitefly | **NOT REGISTERED on cotton** — verified; only Okra and Tea entries exist |
| 20 | Multiple | **Re-entry intervals (REI)** | **NOT FOUND — India does not stipulate REI on labels** |
| 21 | Multiple | **Maximum applications per season** | **NOT FOUND on labels for essentially every product listed** |
| 22 | Multiple | **Toxicity triangle colour** | **NOT in CIB&RC MUP** — all colours in this file are ⚠ indicative; read the pack |
| 23 | Multiple | **Trade names** | **NOT in CIB&RC MUP** — all ⚠ indicative |

---

# APPENDIX B — SOURCE DISAGREEMENTS FLAGGED

| Crop / product | Disagreement | Recommended handling |
|---|---|---|
| Potato — Mancozeb 75% | **WP** row gives PHI "-", **WG** row gives PHI 3–5 days, same crop and disease | Advise the longer/safer: **do not harvest within 7 days** |
| Grape — Pyriofenone 18% w/v SC | Listed twice for powdery mildew at 600 ml/ha with **PHI 7 (p.26)** and **PHI 5 (p.34)** | Advise **7 days** |
| Onion — purple blotch | CIB&RC has **no straight-mancozeb** entry; PAU/TNAU/ANGRAU packages routinely recommend mancozeb 0.25% | Record both; label the SAU advice **off-label** |
| Sugarcane — red rot | CIB&RC has **one** registered product; SAU packages recommend carbendazim sett dip + MHAT | Record both; label carbendazim **off-label**; MHAT is non-chemical and safe to recommend |
| Onion / Chilli — dose basis | Some entries give **%/per-100-L**, others give **per-ha** | Always carry both; never convert one into the other without stating the spray volume assumed |

---

# APPENDIX C — WHAT THE DEVICE SHOULD SAY EVERY TIME

1. **Read the triangle and the label on the container.** The label overrides everything here.
2. **Give the % with the molecule, always.** "Chlorantraniliprole" is meaningless;
   "Chlorantraniliprole 18.5% SC" is a dose. The 18.5% and 47.85% products differ 2.6×.
3. **Lead with the PHI**, not the dose — it is the number that decides whether the produce
   is safe and saleable, and it is the number farmers are never told.
4. **Measure, don't estimate.** A capful is not a dose. Give the per-tank figure
   (dose ÷ spray volume × tank size) as well as the per-acre figure.
5. **Protective equipment:** full-sleeve clothing, face cover, gloves; spray with the wind
   at your back; never blow out a blocked nozzle with your mouth; bathe and change clothes
   after spraying; never eat, drink or smoke while spraying.
6. **Never re-use a pesticide container** for water, food or fuel. Triple-rinse, puncture,
   and bury away from water sources.
7. **Bees:** avoid spraying any crop in flower during bee-flight hours. Applies especially
   to mustard, mango at bloom, and all cucurbits.
8. **Rotate modes of action** (IRAC / FRAC group numbers), and stop spraying below the
   economic threshold. Resistance is what turns a ₹500 spray into a ₹5,000 spray programme.
9. **When in doubt, say "I don't know — ask your KVK / State Agriculture Department."**
   A wrong dose is worse than no answer.

---

# SOURCES USED

1. **CIB&RC / DPPQS — Major Uses of Pesticides (INSECTICIDES), upto 31/03/2026** —
   https://ppqs.gov.in/sites/default/files/updated_mup_insecticide_as_on_31.03.2026_c.pdf
   *(primary source for every insecticide/acaricide dose, target and PHI in this file)*
2. **CIB&RC / DPPQS — Major Uses of Pesticides (FUNGICIDES), upto 31/03/2026** —
   https://ppqs.gov.in/sites/default/files/2._chemical_mup_fungicide_as_on_31.03.2026_0.pdf
   *(primary source for every fungicide/bactericide dose, target and PHI in this file)*
3. **CIB&RC — Major Uses of Pesticides index page** —
   https://ppqs.gov.in/divisions/cib-rc/major-uses-of-pesticides
4. **CIB&RC — Major Uses of Pesticides (BIO-PESTICIDES / Bio-fungicides), 31/03/2026** —
   https://ppqs.gov.in/sites/default/files/3._bio_pesticide_mup_biofungicide_as_on_31.03.2026.pdf
   *(referenced for Trichoderma; rates NOT extracted this pass)*
5. **CIB&RC — Major Uses of Pesticides (BIO-INSECTICIDES), 31/03/2026** —
   https://ppqs.gov.in/sites/default/files/6._mup_bio_insecticide_31.03.2026.pdf
   *(referenced for HaNPV; rates NOT extracted this pass)*
6. **CIB&RC — Registered Products / CROP database** —
   https://ppqs.gov.in/divisions/cib-rc/registered-products
   *(for verifying that a specific brand/formulation is currently registered)*
7. **TNAU Agritech Portal — Crop Protection, Major use of fungicides (CIB&RC extract)** —
   https://agritech.tnau.ac.in/crop_protection/pdf/6_Major_use_fungicides.pdf
   ⚠ *TNAU's certificate was expired at time of access; the mirror was not used for any
   dose in this file — all doses come from ppqs.gov.in directly.*
8. **NIPHM / DPPQS — AESA-based IPM Packages of Practice** —
   https://niphm.gov.in/IPMPackages/ *(referenced for IPM/ETL context; no dose taken)*

**Method note:** the two CIB&RC PDFs were downloaded from ppqs.gov.in and their tables
extracted cell-by-cell, so every dose here is the table cell as printed, not a paraphrase.
Where a cell was blank, merged, or internally inconsistent, it is flagged ⚠ rather than
filled in.

⚠ **Corroboration limit — be honest about this.** Every dose in this file rests on the
**single** authoritative source (CIB&RC MUP, sources 1 and 2). Independent
cross-verification against a **second** source (NIPHM AESA packages, PAU/TNAU/ANGRAU
Package of Practices) **was attempted but not completed** — niphm.gov.in returned HTTP 403,
the ppqs IPM package index returned HTTP 404, and the TNAU mirror had an expired TLS
certificate. Since CIB&RC *is* the legal registration authority and the SAU packages are
derived from it (and frequently go beyond it, as the flagged off-label cases show), a
single-source position is defensible here — but the ⚠ items in Appendix A and B
specifically need a second pair of eyes on a physical container label before they are
used to advise a farmer.

**Not covered in this pass (deliberately, as out of the requested scope):**
herbicides; plant growth regulators; bio-pesticide dose rates; nematicides; rodenticides;
storage/fumigation; and the current banned/restricted pesticide notifications under
Section 27 of the Insecticides Act — **that ban list must be checked separately and
enforced as a hard filter before any of these recommendations is served to a farmer.**
