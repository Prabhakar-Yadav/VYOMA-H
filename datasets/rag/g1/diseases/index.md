---
type: Directory Index
title: Pest and disease concepts
description: Conditions the device can diagnose, with symptom text written for retrieval matching against vision model output.
tags: [diseases, pests, diagnosis]
---

# Pest and disease concepts

Each concept's `# Visual symptoms` section is written deliberately in the register
a vision model uses when describing a photograph — colour, shape, position on the
plant, texture, pattern. This is what the retriever matches against.

The `# Distinguishing from similar conditions` section carries the confusable
pairs. These are where a small vision model fails most often, and where a wrong
answer costs the most.

## Conditions

| Condition | Crop | Urgency | Defining visual sign |
|---|---|---|---|
| [Cotton whitefly](cotton-whitefly.md) | Cotton | Moderate | White flies under leaf + sticky coating + black sooty mould |
| [Tomato late blight](tomato-late-blight.md) | Tomato | **High** | Water-soaked dark patches, **no rings**, white fuzz underneath |
| [Tomato early blight](tomato-early-blight.md) | Tomato | Moderate | Brown spots with **concentric rings**, on lower leaves first |
| [Rice bacterial leaf blight](rice-bacterial-leaf-blight.md) | Rice | Moderate | Yellow lesions from leaf tip with **wavy margins**, bacterial ooze |
| [Maize fall armyworm](maize-fall-armyworm.md) | Maize | **High** | Ragged holes + **moist sawdust frass in the whorl** |
| [Wheat yellow rust](wheat-yellow-rust.md) | Wheat | **High** | Yellow powdery pustules in **straight stripes** along veins |

## Known confusable pairs

These must be handled correctly or the recommendation is actively harmful:

| Pair | Consequence of confusing them |
|---|---|
| Early blight ↔ Late blight | Late blight moves 10× faster. Treating it as early blight loses the field. |
| Bacterial leaf blight ↔ Rice blast | BLB is bacterial — **a fungicide does nothing**. Money spent, crop lost. |
| Yellow rust ↔ Brown rust | Different urgency and different varietal advice. |
| Whitefly ↔ Jassid | Different insecticide class entirely. |

## Coverage gap

Six conditions across five crops is a demonstration corpus, not a deployable one.
A district-level deployment needs roughly 40–60 conditions covering that
district's actual cropping pattern. **Anything outside this list must trigger
abstention, not a guess.**
