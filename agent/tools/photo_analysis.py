"""Single vision entry point: classify the photo, then run the matching detailed pass.

Two ollama.chat calls per photo — a cheap classification pass (one word: PESTICIDE,
CROP, or OTHER) followed by the detailed extraction pass tuned for whichever it is.
Pushing the crop-vs-pesticide decision into the vision model (which actually sees the
pixels) is far more reliable than asking the text tool-calling model to guess it blind
from the farmer's wording alone — see the notebook markdown for the measured
comparison. Also more reliable than asking the model to classify AND conditionally
run one of several detailed formats in a single call — tested and rejected, see
notebook (it either answered every branch's template at once, or hallucinated details
from a different photo's format).

2026-08-14: `analyze_photo_hybrid()` below is the real production replacement for the
plain `analyze_photo()` above (see its own docstring) -- kept both in the file, the old
one as a reference/fallback, not because both are still live call sites.

2026-08-14 v3 (same day, after the 21-image A/B test): fixed a real misclassification bug
(a pest-on-a-leaf photo classified "pesticide"), a real bracket/list-artifact bug in
descriptions, and shortened the crop-description instructions -- see the comment above
`_build_classify_and_describe_prompt` for the full evidence. Also added optional
`user_context` (the farmer's real turn text, agent-bound not model-authored) as a second
disambiguation signal for the classify step.

2026-08-14 v4 (same day): `analyze_photo_unified()` is a TRUE single call for every photo,
pesticide included -- by direct instruction, after `analyze_photo_hybrid`'s own pesticide
path turned out to cost MORE than the old 2-call version (its first call still writes a full
description that gets thrown away for pesticide). This reopens the hallucination risk the
hybrid design was built to close; accepted as a real, known tradeoff, not rediscovered blind
-- see the comment above `_UNIFIED_SCHEMA`. `analyze_photo`/`analyze_photo_hybrid` are left
in this file as reference/fallback, same as before.
"""

import re

import ollama


def analyze_photo(
    image_path,
    focus_question: str,
    classify_prompt: str,
    crop_prompt: str,
    label_prompt: str,
    generic_prompt: str,
    model: str = "gemma4:e2b",
    keep_alive: int = -1,
    num_ctx: int = 8192,
    temperature: float = 0.2,
    think: bool | str = False,
) -> str:
    if image_path is None:
        return "No image was attached to this message — nothing to analyze."

    def _chat(prompt: str) -> str:
        response = ollama.chat(
            model=model,
            messages=[{
                "role": "user",
                "content": prompt,
                "images": [str(image_path)],
            }],
            think=think,
            keep_alive=keep_alive,
            options={"num_ctx": num_ctx, "temperature": temperature},
            stream=False,
        )
        return response.message.content

    classification = _chat(classify_prompt).strip().upper()

    if "PESTICIDE" in classification:
        return _chat(label_prompt)
    if "CROP" in classification:
        return _chat(crop_prompt.format(focus_question=focus_question))
    return _chat(generic_prompt)


# 2026-08-14: real, evidence-based HYBRID replacement -- not a blanket merge. A real 7-image
# A/B test (crop/pesticide/other, all 3 categories) of a naive full single-call merge (classify
# + conditional extraction, schema-constrained) against the old 2-call version found a real,
# meaningful speed win (1.24-3.58x per image, 1.87x overall on that batch) BUT two real
# accuracy problems specifically on the pesticide-label path: (1) a real, concerning
# hallucination -- one label the old 2-call version correctly reported as too blurry to read
# ("Active ingredients: -", with a note explaining why) came back from the single-call version
# with a confident, specific, unverifiable chemical name instead. Given this prompt's own
# explicit safety rule ("a wrong chemical name could lead a farmer to use an unsafe dose"),
# this is a real, unacceptable regression for this one category, not a minor discrepancy --
# (2) crop/other descriptions from the merged call also came back shorter and less detailed
# than the old version's (missing severity/progression nuance `plant_disease_lookup` likely
# benefits from), a real but lower-stakes quality regression.
#
# The fix: classify+describe in ONE real call (`_classify_and_describe`) for every photo, same
# as before -- but if that call's own classification comes back "pesticide", DISCARD its
# extraction and make a real SECOND call using the exact original, already-safety-tested
# `label_prompt` (byte-identical prompt/behavior to the old analyze_photo() for this one
# category). Net effect: crop/other (the common, lower-stakes cases) drop to a genuine single
# real call; pesticide (the rare, highest-stakes case, where a wrong answer has real
# consequences) costs exactly what it always did -- no regression, because nothing about its
# real code path changed. This is a real, measured compromise, not a guess -- see
# `analyze_photo_hybrid()`'s own docstring for how to call it.
_CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": ["pesticide", "crop", "other"]},
        "description": {"type": "string"},
    },
    "required": ["category", "description"],
}


# 2026-08-14 v3: two real fixes from the 21-image v2 test's own results (not guesses):
#
# (1) MISCLASSIFICATION -- `insect.jpg` (a leaf with a bug on it) was classified "pesticide"
# and got a nonsense label-extraction answer back ("Brand/product name: not visible..."). The
# old wording only said what "pesticide" positively was; it never said what it explicitly is
# NOT, so a pest-on-a-plant photo could plausibly slide into either bucket. Fixed by (a) an
# explicit negative example ("a bug ON a plant is NOT pesticide") and (b) accepting an optional
# `user_context` -- the farmer's own real words for this turn, bound in by the caller (see
# analyze_photo_hybrid's docstring), NOT re-derived by the vision model itself. This is a second,
# independent signal beyond the pixels: a farmer asking about a bug on their leaf is strong
# evidence for "crop", even on an ambiguous frame.
#
# (2) BRACKET/LIST ARTIFACTS -- several v2 descriptions came back as "[1] ... [2] ... [3] ..."
# or with a stray leading "[". Root cause, not just a symptom: the old prompt's own instructions
# were a "1. 2. 3. 4." numbered list, and the model mirrored that structure into its actual
# answer text despite the field being declared a plain string. Fixed at the source by rewriting
# the instructions as flowing prose (no numbered list for the model to imitate), plus an explicit
# "ONE plain paragraph, NO lists, NO numbering, NO brackets" instruction, plus a post-processing
# safety net (`_clean_description` below) in case the model does it anyway.
#
# Also shortened materially (see module docstring's timing note) -- the 4-part enumerated
# instruction was pushing the model toward a long, itemized answer, which is exactly the
# generation-time cost that was eating most of the call-elimination savings. This version keeps
# the same required content (part/zone, color/pattern/texture, severity/spread -- the vocabulary
# calibrated against datasets/rag/g1/diseases/*.md) but asks for it as 2-3 tight sentences
# instead of 3-4 verbose ones structured around a checklist.
def _build_classify_and_describe_prompt(focus_question: str, user_context: str | None = None) -> str:
    context_block = ""
    if user_context:
        context_block = (
            f"The farmer's own message for this photo: \"{user_context}\"\n"
            "Use this as a second signal for the category decision and for what to focus on "
            "-- e.g. a plant with visible pests/damage is still \"crop\", not \"pesticide\", "
            "even if the farmer is asking about a bug or a spray for it.\n\n"
        )
    return (
        context_block +
        "Look at this photo and respond with the requested JSON fields.\n\n"
        "First decide the category:\n"
        "- \"pesticide\": ONLY an actual pesticide/agrochemical PRODUCT in frame -- a bottle, "
        "packet, sachet, can, or printed label; the packaging itself is what's photographed.\n"
        "- \"crop\": a crop, plant, leaf, or field (vegetation growing or harvested) -- "
        "INCLUDING one with visible pests, insects, or disease damage on it. A bug or lesion "
        "ON a plant is still \"crop\", never \"pesticide\", even if the farmer's question is "
        "about that pest or about spraying something. Farm ANIMALS (cows, cattle, buffalo, "
        "goats, poultry, etc.) are \"other\", not \"crop\", even when photographed on a farm.\n"
        "- \"other\": anything that is not one of those two.\n\n"
        "Then write \"description\" as ONE plain paragraph -- 2-3 sentences, NO lists, NO "
        "numbering, NO brackets:\n"
        f"- If \"crop\": focus on {focus_question}. Name the crop/plant if identifiable; "
        "EXACTLY where the symptom is (part -- leaf/stem/tuber/fruit -- and zone -- tip vs "
        "margin, old vs young growth, upper vs underside -- this single detail is often the "
        "difference between two similar-sounding conditions); the real color(s)/halo/ring, "
        "shape, and texture (water-soaked, dry/papery, powdery, sunken) instead of vague words "
        "like \"brown spot\"; and severity/spread (isolated vs widespread/coalescing). This "
        "feeds a disease-database search, so be specific and plainly-visible, not a diagnosis "
        "-- do not name a specific disease.\n"
        "- If \"pesticide\": a one-sentence placeholder is fine here (e.g. \"pesticide product "
        "label\") -- the real label extraction happens in a separate step.\n"
        "- If \"other\": 2-3 factual sentences on what's actually shown (objects, setting, "
        "visible text). Do not force this into a farming diagnosis if that's not what's shown."
    )


def _coerce_text(value) -> str:
    """Defensive against a real, observed quirk: structured output occasionally returns a
    string-typed field as a single-item JSON array instead (e.g. `["some text"]`) despite the
    schema declaring it a plain string. Confirmed directly in the real A/B test -- happened on
    2 of 7 real images. Joins a list/tuple back into plain text rather than let a caller show
    a literal `["..."]` to a real farmer."""
    if isinstance(value, (list, tuple)):
        return " ".join(str(v) for v in value if v)
    return str(value) if value is not None else ""


_BRACKET_MARKER_RE = re.compile(r"\[\s*\d+\s*\]\s*")


def _clean_description(text: str) -> str:
    """Belt-and-suspenders against the bracket/list-marker artifact confirmed in the v2 test
    (e.g. "[1] ... [2] ..." or a stray leading "["), on top of the prompt's own "NO lists, NO
    brackets" instruction -- see the big comment above `_build_classify_and_describe_prompt`
    for the real root cause. Strips numbered markers first, then any leftover bare brackets."""
    text = _BRACKET_MARKER_RE.sub("", text)
    text = text.replace("[", "").replace("]", "")
    return re.sub(r"\s+", " ", text).strip()


def _classify_and_describe(image_path, focus_question, user_context, model, keep_alive, num_ctx, temperature, think):
    response = ollama.chat(
        model=model,
        messages=[{
            "role": "user",
            "content": _build_classify_and_describe_prompt(focus_question, user_context),
            "images": [str(image_path)],
        }],
        format=_CLASSIFY_SCHEMA,
        think=think,
        keep_alive=keep_alive,
        options={"num_ctx": num_ctx, "temperature": temperature},
        stream=False,
    )
    import json
    try:
        parsed = json.loads(response.message.content)
    except (json.JSONDecodeError, TypeError) as exc:
        return None, f"(analyze_photo_hybrid: failed to parse structured output: {exc}) raw={response.message.content!r}"
    category = _coerce_text(parsed.get("category")).strip().lower()
    description = _clean_description(_coerce_text(parsed.get("description")).strip())
    return category, description


# 2026-08-14: capped hard here, not left to the caller, so a caller that forwards the farmer's
# full raw transcript (rather than a trimmed one) can't silently blow up prompt size/latency --
# see agent.py's `_build_dispatch` for why the caller passes the real, un-trimmed turn text.
_USER_CONTEXT_MAX_CHARS = 220


def analyze_photo_hybrid(
    image_path,
    focus_question: str,
    label_prompt: str,
    user_context: str | None = None,
    model: str = "gemma4:e2b",
    keep_alive: int = -1,
    num_ctx: int = 8192,
    temperature: float = 0.2,
    think: bool | str = False,
) -> str:
    """Real production replacement for analyze_photo() above -- same real safety-tested
    behavior for the pesticide-label path (needs `label_prompt`, the same one analyze_photo()
    takes), one real call instead of two for crop/other. See the module-level comment above
    this function for the full real evidence behind this specific design.

    `user_context`: the farmer's own text for this turn (agent.py binds this from `run_turn`'s
    `user_text`, the same way `image_path` is already bound -- not something the tool-calling
    model authors itself, so it costs nothing extra in that model's own generation). Used only
    as a second disambiguation signal alongside the pixels (see `_build_classify_and_describe_
    prompt`'s comment for the real misclassification bug this fixes) -- optional, None/"" is a
    normal, fully-supported case (voice-only turns with no useful photo context, or callers that
    haven't been updated to pass it yet)."""
    if image_path is None:
        return "No image was attached to this message — nothing to analyze."

    if user_context and len(user_context) > _USER_CONTEXT_MAX_CHARS:
        user_context = user_context[:_USER_CONTEXT_MAX_CHARS].rsplit(" ", 1)[0] + "…"

    category, description = _classify_and_describe(
        image_path, focus_question, user_context, model, keep_alive, num_ctx, temperature, think,
    )
    if category is None:
        return description  # description holds the real parse-failure message in this case

    if category == "pesticide":
        response = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": label_prompt, "images": [str(image_path)]}],
            think=think,
            keep_alive=keep_alive,
            options={"num_ctx": num_ctx, "temperature": temperature},
            stream=False,
        )
        return response.message.content

    return description or "(no description returned)"


# ---------------------------------------------------------------------------
# 2026-08-14 v4: back to a TRUE single call, every photo, no pesticide exception -- by direct
# instruction, after walking through exactly why the hybrid design above pays extra for
# pesticide (its first call still writes a full schema'd description that gets thrown away
# for pesticide, so it costs MORE than the old one-word classify + label call, not less).
#
# This reopens the risk `analyze_photo_hybrid` was built to close: the very first attempt at a
# single call (superseded, not kept in this file) hallucinated a chemical name on a blurry
# label instead of saying "not visible" like the safety-tested version always did. Per direct
# instruction, that risk is accepted here as a known, real tradeoff (an occasional wrong/
# missed extraction is "not the end of the world"), in exchange for every photo -- pesticide
# included -- costing exactly one call. Two things differ from that first, rejected attempt,
# which may (not guaranteed to) reduce the risk without eliminating it:
#   1. The label-extraction safety rules (never guess a chemical from brand recognition, write
#      "not visible" rather than guess, no percentage/formulation codes, split combinations
#      onto separate lines) are reproduced verbatim from `LABEL_VISION_PROMPT` in the single
#      prompt below, not a shortened paraphrase.
#   2. `user_context` (the farmer's real words, see `analyze_photo_hybrid`'s docstring) is a
#      real extra signal the first attempt never had access to.
# If real testing surfaces the same hallucination class again, that is expected and should be
# reported as such, not treated as a new surprise -- see `test_photo_analysis_hybrid_v3.py`'s
# successor test for the real comparison.
# 2026-08-14, post-mortem on a real 21m34s production incident (image-audio-test-suite's
# rust_leaves case): Ollama's own server log (`journalctl -u ollama`) showed this call's task
# actively, continuously generating tokens the WHOLE time (432 print_timing lines, steady
# ~25-26 tok/s, never stalled/blocked) until it hit `stop processing: n_tokens = 32767,
# truncated = 1` -- it filled the entire 32768-token context window before ever closing the
# JSON, so the truncated result failed to parse. Two real, independent contributing causes,
# both fixed here (see analyze_photo_unified's own `think=False` for the second):
#   1. Every string field below was UNBOUNDED (`{"type": "string"}`, no length limit) -- a
#      grammar-constrained decoder has nothing telling it to ever close a string field once
#      inside one, so an unlucky low-temperature repetition loop can run indefinitely. Fixed
#      via `maxLength` below -- confirmed (websearch, ggml-org/llama.cpp's own
#      json_schema_to_grammar.py) that llama.cpp's grammar compiler DOES turn `maxLength` into
#      a real bounded repetition rule (`char{0,N}`) -- but ALSO confirmed a real llama.cpp bug
#      (ggml-org/llama.cpp#25923): the grammar engine hard-caps any single repetition count at
#      2000, and a maxLength set anywhere near/above that makes grammar compilation FAIL
#      outright rather than degrade gracefully. `maxLength` is Unicode CHARACTERS (JSON Schema
#      spec), not words or tokens. `description`'s 900 is evidence-based, not guessed: measured
#      across 34 real crop/other descriptions from the v3/v4 A/B tests, max observed was 488
#      chars, median 315 -- 900 gives ~1.84x headroom over anything actually produced, while
#      staying comfortably under the 2000 grammar-compile-failure ceiling. The shorter fields
#      (brand/manufacturer/active_ingredients/notes) needed less real-world headroom by their
#      own nature (short label text, not free prose) and are unchanged.
#   2. `format=` (structured output) and `think=` are documented as genuinely incompatible in
#      Ollama itself (ollama/ollama#10538: format suppresses the `<think>` token's probability
#      entirely; ollama/ollama#15260: real reports of the REVERSE failure too -- the format
#      grammar constraint getting silently ignored when combined with thinking, for at least
#      one model family). `analyze_photo_unified` used to inherit `think=self.think` from the
#      calling agent (config.AGENT_THINK="medium" by default) -- every one of this project's
#      own ~40 isolated test calls used think=False and never once reproduced this; the one
#      real production incident happened on a call that inherited "medium". Very likely the
#      actual mechanism: the format constraint got silently dropped for that call, so there
#      was no grammar at all stopping it, not just an unbounded field within a working one.
_UNIFIED_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": ["pesticide", "crop", "other"]},
        "description": {"type": "string", "maxLength": 900},
        "brand": {"type": "string", "maxLength": 150},
        "active_ingredients": {"type": "string", "maxLength": 400},
        "manufacturer": {"type": "string", "maxLength": 150},
        "notes": {"type": "string", "maxLength": 300},
    },
    "required": ["category", "description", "brand", "active_ingredients", "manufacturer", "notes"],
}


def _build_unified_prompt(focus_question: str, user_context: str | None = None) -> str:
    context_block = ""
    if user_context:
        context_block = (
            f"The farmer's own message for this photo: \"{user_context}\"\n"
            "Use this as a second signal for the category decision and for what to focus on "
            "-- e.g. a plant with visible pests/damage is still \"crop\", not \"pesticide\", "
            "even if the farmer is asking about a bug or a spray for it.\n\n"
        )
    return (
        context_block +
        "Look at this photo. Think carefully about which of the three tasks below it actually "
        "calls for, then respond with the requested JSON fields. Fields that belong to a task "
        "you did NOT pick must be left as an empty string \"\" -- do not fill them with "
        "guesses or unrelated content.\n\n"
        "First decide the category:\n"
        "- \"pesticide\": ONLY an actual pesticide/agrochemical PRODUCT in frame -- a bottle, "
        "packet, sachet, can, or printed label; the packaging itself is what's photographed. "
        "This is a careful OCR/label-reading task, not a description task.\n"
        "- \"crop\": a crop, plant, leaf, or field (vegetation growing or harvested) -- "
        "INCLUDING one with visible pests, insects, or disease damage on it. A bug or lesion "
        "ON a plant is still \"crop\", never \"pesticide\", even if the farmer's question is "
        "about that pest or about spraying something. Farm ANIMALS (cows, cattle, buffalo, "
        "goats, poultry, etc.) are \"other\", not \"crop\", even when photographed on a farm.\n"
        "- \"other\": anything that is not one of those two.\n\n"
        "IF CROP: fill \"description\" with ONE plain paragraph, 2-3 sentences, NO lists, NO "
        f"numbering, NO brackets. Focus on {focus_question}. Name the crop/plant if "
        "identifiable; EXACTLY where the symptom is (part -- leaf/stem/tuber/fruit -- and "
        "zone -- tip vs margin, old vs young growth, upper vs underside -- this single detail "
        "is often the difference between two similar-sounding conditions); the real "
        "color(s)/halo/ring, shape, and texture (water-soaked, dry/papery, powdery, sunken) "
        "instead of vague words like \"brown spot\"; and severity/spread (isolated vs "
        "widespread/coalescing). This feeds a disease-database search, so be specific and "
        "plainly-visible, not a diagnosis -- do not name a specific disease. Leave \"brand\", "
        "\"active_ingredients\", \"manufacturer\", \"notes\" empty.\n\n"
        "IF PESTICIDE: fill \"brand\" (name as printed, or \"not visible\"), "
        "\"active_ingredients\" (chemical name(s) ONLY, one per line each prefixed \"- \", or "
        "\"not visible\"), \"manufacturer\" (name if shown, or \"not visible\"), and \"notes\" "
        "(one short sentence, e.g. if blurry or you are unsure). Rules for "
        "active_ingredients:\n"
        "  - Only report a chemical name if you can actually read its printed letters in this "
        "image. NEVER report a chemical name from general knowledge of the brand, even if you "
        "recognize the brand and think you know its usual active ingredient.\n"
        "  - Write ONLY the chemical/active-ingredient name (e.g. \"Chlorpyrifos\"), not the "
        "percentage, w/w, or formulation code (EC, SL, WP, G, 3G, SC, etc.), not the brand "
        "name.\n"
        "  - If the label shows a combination (e.g. \"Chloropyriphos 50% + Cypermethrin 5% "
        "EC\"), list each chemical on its own line.\n"
        "  - Fix obvious OCR-style spelling only if confident it's the same word.\n"
        "  - If the active-ingredient text is too small, blurry, cropped, or simply not "
        "printed, write exactly: not visible\n"
        "  - It is much better to say \"not visible\" than to guess wrong -- a wrong chemical "
        "name here could lead a farmer to use an unsafe dose.\n"
        "Also fill \"description\" with ONE short factual sentence about what's visibly in "
        "the photo (container type/color, setting) -- useful context even when the label "
        "itself can't be read, but NOT a place to restate or guess at the active ingredient.\n\n"
        "IF OTHER: fill \"description\" with 2-3 factual sentences on what's actually shown "
        "(objects, setting, visible text). Do not force this into a farming diagnosis or a "
        "pesticide-label extraction if that's not what's shown. Leave \"brand\", "
        "\"active_ingredients\", \"manufacturer\", \"notes\" empty."
    )


def _format_label_fields(description: str, brand: str, active_ingredients: str, manufacturer: str, notes: str) -> str:
    """Same 4-line label shape the old label_prompt always returned, PLUS a "Product
    description" line on top (2026-08-14: added since the unified call already generates it
    for free -- no separate discarded call to justify skipping it anymore, see
    analyze_photo_unified's docstring). Nothing in this codebase regex-parses this text --
    it's read by the tool-calling model as a normal tool-result message, not code -- so an
    extra leading line is safe to add without breaking any existing caller."""
    lines = []
    if description:
        lines.append(f"Product description: {description}")
    lines += [
        f"Brand/product name: {brand or 'not visible'}",
        f"Active ingredients: {active_ingredients or 'not visible'}",
        f"Manufacturer: {manufacturer or 'not visible'}",
        f"Notes: {notes}",
    ]
    return "\n".join(lines).rstrip()


def analyze_photo_unified(
    image_path,
    focus_question: str,
    user_context: str | None = None,
    model: str = "gemma4:e2b",
    keep_alive: int = -1,
    num_ctx: int = 8192,
    temperature: float = 0.2,
    think: bool | str = False,
) -> str:
    """TRUE single-call replacement for analyze_photo()/analyze_photo_hybrid() -- exactly one
    ollama.chat() call for every photo, no exception for pesticide. See the big comment above
    `_UNIFIED_SCHEMA` for the real tradeoff this reopens and why it was accepted anyway, and
    for the real 21m34s production incident (rust_leaves, image-audio-test-suite) that led to
    the maxLength/think/num_predict fixes below.

    `think` (the parameter): kept in the signature for flexibility/testing, but IGNORED below
    -- this call always forces think=False regardless of what's passed. Not a guess: Ollama's
    own tracker documents `format=` (structured output) and `think=` as genuinely incompatible
    (ollama/ollama#10538, #15260 -- format can silently drop the grammar constraint entirely
    when combined with thinking), and the real incident above happened on a call that had
    inherited think="medium" from the calling agent's own default -- every one of this
    project's ~40 isolated test calls used think=False and never reproduced it. A caller
    genuinely needing the vision model to "think" should use a different, unconstrained
    (non-`format=`) call instead of asking this one to do both at once.

    `user_context`: same meaning/cap as `analyze_photo_hybrid`'s -- the farmer's real turn
    text, agent-bound (see agent.py's `_build_dispatch`), not model-authored."""
    if image_path is None:
        return "No image was attached to this message — nothing to analyze."

    if user_context and len(user_context) > _USER_CONTEXT_MAX_CHARS:
        user_context = user_context[:_USER_CONTEXT_MAX_CHARS].rsplit(" ", 1)[0] + "…"

    response = ollama.chat(
        model=model,
        messages=[{
            "role": "user",
            "content": _build_unified_prompt(focus_question, user_context),
            "images": [str(image_path)],
        }],
        format=_UNIFIED_SCHEMA,
        think=False,  # see docstring above -- deliberately not `think` (the parameter)
        keep_alive=keep_alive,
        options={
            "num_ctx": num_ctx,
            "temperature": temperature,
            # Hard backstop (2026-08-14), independent of whether maxLength/think=False above
            # actually close the gap -- num_predict is enforced by the sampling loop itself,
            # not by grammar/schema translation correctness, so it bounds generation length no
            # matter what else goes wrong. 1024 (schema's own max possible content is
            # 900+150+400+150+300 = 1900 chars =~ 500-550 tokens of English text plus JSON
            # structure overhead -- real ~2x headroom, not tight) at this project's observed
            # 20-26 tok/s generation rate gives a worst-case ceiling of ~40-51s if ever fully
            # used -- nowhere near the 21m34s/31,257 tokens the real incident generated before
            # being cut off by the full context window instead, and typical calls finish in
            # 4-10s same as before (num_predict only bounds the ceiling, doesn't slow normal
            # generation down).
            "num_predict": 1024,
        },
        stream=False,
    )
    import json
    try:
        parsed = json.loads(response.message.content)
    except (json.JSONDecodeError, TypeError) as exc:
        return f"(analyze_photo_unified: failed to parse structured output: {exc}) raw={response.message.content!r}"

    category = _coerce_text(parsed.get("category")).strip().lower()

    if category == "pesticide":
        return _format_label_fields(
            _clean_description(_coerce_text(parsed.get("description")).strip()),
            _coerce_text(parsed.get("brand")).strip(),
            _coerce_text(parsed.get("active_ingredients")).strip(),
            _coerce_text(parsed.get("manufacturer")).strip(),
            _coerce_text(parsed.get("notes")).strip(),
        )

    description = _clean_description(_coerce_text(parsed.get("description")).strip())
    return description or "(no description returned)"
