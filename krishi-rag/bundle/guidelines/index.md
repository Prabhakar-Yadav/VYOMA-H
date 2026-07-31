---
type: Directory Index
title: Government schemes and official guidance
description: Central and state schemes, eligibility and how to apply, plus official best-practice guidance on safety, soil testing and where to get help.
tags: [schemes, government, guidelines, safety, subsidy]
source_type: govt_guideline
---

# Government schemes and official guidance

Two kinds of content, both from official sources only.

## 1. Schemes

PM-KISAN, Fasal Bima, Kisan Credit Card, Soil Health Card, irrigation and
mechanisation subsidies, e-NAM, and the rest. For each: what it gives, who
qualifies, what documents are needed, and what the farmer actually does next.

**This is the highest-value non-diagnostic thing the device can carry.** A farmer
who does not know a subsidy exists cannot claim it, and eligibility rules are
exactly the kind of detail a language model invents confidently and wrongly.

## 2. Official practice guidance

Safe pesticide handling and the label triangle colours, pre-harvest intervals and
why residue limits exist, poisoning first response and the National Poison
Information Centre number, soil sampling and reading a Soil Health Card, seed
treatment, when to approach a KVK, the Kisan Call Centre, and MSP basics.

## Why scheme answers must be grounded

Scheme rules carry **numbers, dates, eligibility cut-offs and document lists** —
every one of them something a farmer will act on. Under the routing rule, any
answer carrying a number or an official instruction is retrieved, never
generated. A model asked "am I eligible for PM-KISAN" will produce a fluent,
plausible, wrong answer, and the farmer discovers the error at the bank counter.

## ⚠ Freshness

**Scheme rules change.** Amounts, deadlines and eligibility are revised between
budgets, and several schemes vary by state. Every concept here carries
`last_modified` on its source, and stale entries should be re-checked rather than
trusted. Where a rule is state-specific, the concept says so instead of implying
a national rule.

## Writing rule

The device reads this aloud, so write short concrete sentences describing what
the farmer does, in order. State conditions **positively** — "eligible if the
landholding is recorded in the farmer's name" rather than "not eligible without
land records" — because negation breaks vector search.
