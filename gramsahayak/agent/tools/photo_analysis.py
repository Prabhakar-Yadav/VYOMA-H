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
"""

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
