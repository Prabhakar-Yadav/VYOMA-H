---
type: Directory Index
title: Treatment label records
description: CIB&RC-referenced pesticide label records. The sole legitimate source of any dose the device speaks aloud.
tags: [treatments, labels, cibrc]
---

# Treatment label records

**The grounding contract.** A `Treatment` concept is the only place a dose,
dilution, pre-harvest interval, or safety instruction may come from. The vision
model may describe what it sees; it may never author a prescription. Every
emitted recommendation carries the `label_id` of the concept it came from, and
the emitter refuses to speak without one.

## Records

| Product | Molecule | Triangle | Dose/acre | Mix rate | PHI | Treats |
|---|---|---|---|---|---|---|
| [Diafenthiuron 50% WP](diafenthiuron-50-wp.md) | Diafenthiuron | 🟨 Yellow | 240 g | 1.2 g/L | 21 d | Cotton whitefly |
| [Cymoxanil 8% + Mancozeb 64% WP](cymoxanil-mancozeb.md) | Cymoxanil + Mancozeb | 🟦 Blue | 600 g | 3 g/L | 7 d | Tomato late blight |
| [Mancozeb 75% WP](mancozeb-75-wp.md) | Mancozeb | 🟦 Blue | 600 g | 2.5 g/L | 7 d | Tomato early/late blight |
| [Emamectin benzoate 5% SG](emamectin-benzoate-5-sg.md) | Emamectin benzoate | 🟨 Yellow | 80 g | 0.4 g/L | 7 d | Maize fall armyworm |
| [Chlorantraniliprole 18.5% SC](chlorantraniliprole-18-5-sc.md) | Chlorantraniliprole | 🟦 Blue | 60 ml | 0.3 ml/L | 10 d | Maize fall armyworm |
| [Propiconazole 25% EC](propiconazole-25-ec.md) | Propiconazole | 🟨 Yellow | 200 ml | 1 ml/L | 35 d | Wheat rusts |
| [Copper oxychloride 50% WP](copper-oxychloride-50-wp.md) | Copper oxychloride | 🟦 Blue | 1000 g | 3 g/L | 15 d | Rice BLB (suppressive) |

## Verification status

Every record carries `verified: { by: process:cibrc-crosscheck }`, meaning the
molecule and dose were cross-checked against published CIB&RC label claims during
authoring.

**No record has been reviewed by a licensed agronomist.** Under OKF §5.3 these sit
at the *machine-confirmed* tier, not *human-reviewed*. Field deployment requires
promoting them to human-reviewed with a named verifier.
