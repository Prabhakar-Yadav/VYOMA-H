---
type: Directory Index
title: Crop context
description: Crop-level context used to filter retrieval and to resolve local crop names spoken by farmers.
tags: [crops]
---

# Crop context

Crop concepts serve two jobs in retrieval:

1. **Filtering.** If the vision model identifies the crop as cotton, disease
   concepts for rice are excluded before ranking. This removes an entire class of
   cross-crop confusion at near-zero cost.
2. **Name resolution.** Farmers say *kapas*, *narma*, *पत्ती*, *tellagoda*. The
   `local_names` field maps spoken vocabulary onto the canonical crop.

Currently seeded implicitly through the `crop` and `local_names` fields on each
disease concept. Dedicated crop concepts (season, growth stages, spacing) are a
next step once the disease corpus is broader.
