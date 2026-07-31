---
type: Bundle Index
title: Krishi Sahayak Agricultural Knowledge Bundle
description: Offline-first knowledge bundle for crop pest and disease diagnosis, grounded treatment retrieval, and safety guidance for Indian smallholder farmers.
tags: [agriculture, plant-disease, india, offline, bhashini]
generated: { by: human:prabhakar, at: 2026-07-29T00:00:00Z }
---

# Krishi Sahayak Knowledge Bundle

An [OKF v0.2](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
knowledge bundle. Every actionable instruction the device speaks to a farmer is
retrieved verbatim from a concept in this bundle. **The vision model never writes
a dosage.**

## Design contract

| Layer | Responsibility | Source of truth |
|---|---|---|
| Vision model (VLM) | Describe what is visually present: crop, plant part, symptom | Model inference — treated as a *claim*, never as fact |
| This bundle | Identify the condition, name the treatment, state dose, PHI, safety | Curated + verified concept documents |
| Speech layer | Render the retrieved text in the farmer's dialect | Bhashini NMT + TTS |

A response is emitted **only** when a `Treatment` concept was retrieved and its
`label_id` is attached. No `label_id`, no prescription — the device abstains.

## Directory listing

| Path | Contents |
|---|---|
| [diseases/](diseases/index.md) | Pest and disease concepts. Symptom text is written for retrieval matching against VLM visual descriptions. |
| [treatments/](treatments/index.md) | Pesticide / fungicide label records. Dose, dilution, PHI, safety. The only legitimate source of a prescription. |
| [crops/](crops/index.md) | Crop context: season, common local names, growth stages. |
| [safety/](safety/index.md) | Cross-cutting handling, protective equipment, and poisoning-response guidance. |

## Trust status

This bundle is at **prototype trust level**. Concepts carry
`verified: { by: process:cibrc-crosscheck }` where the molecule and dose were
cross-checked against CIB&RC-registered label data, and carry **no** `verified`
field where they have not yet been reviewed.

Per OKF §5.3 an absent `verified` field means *unverified* — not invalid. The
device surfaces this: unverified concepts are gated behind a lower confidence
threshold and trigger the "show this to your KVK" path.

**No concept in this bundle has been reviewed by a licensed agronomist yet.**
That review is a hard prerequisite for any field deployment.

## Change history

See [log.md](log.md).
