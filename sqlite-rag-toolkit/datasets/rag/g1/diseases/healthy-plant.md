---
type: Reference
title: Healthy plant, no disease detected
description: Absorbs queries describing undamaged foliage so that a healthy plant does not get matched onto the nearest disease.
tags: [healthy, no-disease, negative-class]
generated: { by: human:prabhakar, at: 2026-07-29T00:00:00Z }
---

# Visual appearance

- Uniform green colour across the leaf blade, with no yellowing between the veins.
- No spots, no rings, no lesions, no blotches, no patches.
- No holes, no chewed or ragged margins, no tearing.
- No powder, no fuzz, no mould, no sticky coating on the surface.
- No insects visible on either the upper or the lower surface.
- Leaf is flat and firm, not curled, cupped, wilted, or drooping.
- Stems and petioles are clean and undamaged.
- Plant looks normal, fresh, and undamaged overall.

# Why this concept exists

Without a healthy class in the corpus, every retrieval is forced to choose among
diseases, because those are the only candidates. A photo of a perfectly healthy
leaf then matches whichever disease is closest, and the device prescribes a spray
for a plant that does not need one. That is a real harm: wasted money, needless
chemical load, and lost trust the first time a farmer follows the advice and sees
nothing change.

This concept is typed `Reference`, not `Pest` or `Disease`. The emitter only ever
prescribes from `Pest` and `Disease` concepts, so when a healthy query lands here
the pipeline has nothing to prescribe from and abstains by construction rather
than by threshold.

# Response

> This plant looks healthy. I do not see any disease or pest damage.
> Keep watching it, and show it to me again if you notice any change.
