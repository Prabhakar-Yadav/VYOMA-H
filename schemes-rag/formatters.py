from typing import Any, Dict
from config import INTENT_PATTERNS, MAX_LCD_CHARS

def extract_answer_by_intent(user_question: str, scheme: Dict[str, Any]) -> str:
    """Uses compiled regex to select specific information requested by the user and caps length."""
    name = scheme["scheme_name"]

    if INTENT_PATTERNS["documents_required"].search(user_question):
        raw_text = scheme.get("documents_required", "")
        prefix = f"Documents required for {name}: "
    elif INTENT_PATTERNS["eligibility_criteria"].search(user_question):
        raw_text = scheme.get("eligibility_criteria", "")
        prefix = f"Eligibility criteria for {name}: "
    elif INTENT_PATTERNS["how_to_apply"].search(user_question):
        raw_text = scheme.get("how_to_apply", "")
        prefix = f"To apply for {name}: "
    elif INTENT_PATTERNS["benefit_details"].search(user_question):
        raw_text = scheme.get("benefit_details", "")
        prefix = f"Benefits under {name}: "
    else:
        raw_text = scheme.get("benefit_details", "")
        prefix = f"Under {name}: "

    if not raw_text:
        raw_text = scheme.get("benefit_details", "")

    full_response = f"{prefix}{raw_text}".strip()

    # Hard cap at MAX_LCD_CHARS for clean Voice (TTS) & LCD display
    if len(full_response) > MAX_LCD_CHARS:
        full_response = full_response[:MAX_LCD_CHARS - 3].rsplit(" ", 1)[0] + "..."

    return full_response


def format_lcd_display_card(scheme: Dict[str, Any], answer: str, score: float) -> str:
    """Formats the answer for the TFT-LCD screen."""
    return (
        f"=== SCHEME: {scheme['scheme_name'][:25]} ===\n"
        f"ID: {scheme['scheme_id']} | Score: {round(score, 4)}\n"
        f"----------------------------------------\n"
        f"{answer}\n"
        f"----------------------------------------"
    )


def format_voice_text(scheme: Dict[str, Any], answer: str) -> str:
    """Formats the text to be passed to the TTS (Text-To-Speech) pipeline."""
    return f"Regarding {scheme['scheme_name']}: {answer}"
