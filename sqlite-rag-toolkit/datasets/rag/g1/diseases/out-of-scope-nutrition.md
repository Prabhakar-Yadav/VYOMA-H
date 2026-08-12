---
type: Reference
title: Fertiliser and nutrition questions
description: Absorbs fertiliser, manure and nutrient-deficiency questions so they are answered honestly as out of scope instead of being matched onto the nearest pest.
tags: [out-of-scope, fertiliser, nutrition, urea, deficiency, manure]
source_type: scope
generated: { by: human:prabhakar, at: 2026-07-31T00:00:00Z }
---

# What this covers

Questions about feeding the crop rather than protecting it:

- Urea, DAP, MOP, NPK, potash, ammonium sulphate, single super phosphate
- Farmyard manure, compost, vermicompost, green manure
- Micronutrients — zinc, boron, iron, sulphur, magnesium
- How much fertiliser, when to apply it, how many splits, top dressing
- Soil testing and soil health
- Nutrient deficiency symptoms — yellowing from hunger rather than from disease
- Foliar sprays and growth promoters

# Typical questions

Written as farmers actually phrase them, so retrieval matches the question shape
rather than only the topic words.

- How much urea should I apply
- When to apply DAP, when to give the first dose, when to top dress
- How many bags of fertiliser per acre
- What fertiliser for this crop, which NPK ratio
- How much potash, how much zinc, how much boron
- When to give the second and third split
- How much farmyard manure or compost per acre
- Which micronutrient spray, when to spray it
- My leaves are pale and the plant is weak, what should I feed it
- Is my soil short of nitrogen
- How much gypsum, how much lime
- What to apply at sowing, at flowering, at grain filling

# Response

> I do not have verified fertiliser guidance yet. Please ask your Krishi Vigyan
> Kendra, or get a soil test done before applying anything.

# Why this concept exists

Without it, *"how much urea should I put on my cotton"* was reaching the disease
corpus, matching cotton whitefly and cotton jassid on the shared word "cotton",
and refusing through the ambiguity gate. The refusal was safe — no dose was ever
invented — but the farmer heard two pest names in reply to a fertiliser question,
which reads as the device being confused rather than being honest.

This concept gives the question somewhere correct to land.

It is typed `Reference`, not `Pest` or `Disease`, so the emitter has nothing to
prescribe from and abstains by construction rather than by threshold. Same
mechanism as [healthy-plant](healthy-plant.md).

# Why fertiliser advice is genuinely out of scope

A fertiliser recommendation depends on a soil test, the previous crop, the
variety, irrigation, and the season. It is not a lookup the way a pesticide label
is. Giving a national average dose would be confident and frequently wrong, and
over-application costs the farmer money and damages the soil.

Adding this properly means a soil-health corpus keyed to state recommendations,
which is a separate piece of work.
