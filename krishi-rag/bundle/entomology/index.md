---
type: Directory Index
title: Entomology
description: Insect and mite biology — life cycles, seasonal timing, alternate hosts and natural enemies. Explains why a pest is here and when to expect it.
tags: [entomology, insects, mites, biology]
source_type: entomology
---

# Entomology

Symptom identification tells a farmer *what* is on the plant. This corpus tells
them **why it is here, when it will return, and what to remove so it does not.**

That is knowledge neither the farmer nor a 2B vision model reliably holds, which
is exactly the bar for what earns a place in the corpus.

## What belongs here

| Field | Why a farmer needs it |
|---|---|
| Life cycle and stage duration | Tells them how long they have before the next generation |
| Where each stage sits | Where to look, and what to destroy |
| Seasonal peak and weather triggers | Turns reaction into anticipation |
| Off-season survival | Stubble, soil, weed hosts — the thing to clear |
| Alternate and weed hosts | Often the single highest-value cultural action |
| Economic threshold | When spraying is justified, and when it wastes money |
| Natural enemies | What they already have, and how to keep it |
| Virus transmission | Links the insect to a disease they may be treating separately |

## Why this is not a separate tool

All corpora share one index. Corpus boundaries do not match question boundaries:
**whitefly is an insect (here), a cotton pest (`diseases/`), and a virus vector
(`pathology/`)** — the same answer sits in three places. A router would have to
choose before it knows where the answer lives.

One search covers all of them. `source_type` exists for provenance and for
ranking **boosts**, never for hard filtering — a wrong boost still finds the
answer, a wrong filter loses it.

## Writing rule

**State what is present, never what is absent.** Embedding models have no
representation of "not", so "does not overwinter in soil" makes the text *match*
soil-overwintering queries. Write "survives in crop stubble and on weed hosts"
instead.
