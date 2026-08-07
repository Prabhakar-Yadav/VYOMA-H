import os
import sys
import time

# Add ai_tutor_rag directory to path so we can import the engine
sys.path.append(os.path.join(os.path.dirname(__file__), "ai_tutor_rag"))
from ai_tutor_rag import GoogleOKFAITutorEngine

# =====================================================================
# MOCK HARDWARE / API FUNCTIONS (To be replaced with David's real code)
# =====================================================================
def bhashini_stt_api(audio_input: str) -> str:
    """Mock Speech-to-Text: Returns an English translation of village audio."""
    print("[Hardware] 🎤 Received voice input. Running Bhashini STT (Bhojpuri -> English)...")
    time.sleep(0.5)
    return "Why is my shadow so long when I walk home from school in the evening, but short at lunchtime?"

def bhashini_tts_api(text_to_speak: str):
    """Mock Text-to-Speech: Converts text to audio out of the Jetson speaker."""
    print(f"\n[Hardware] 🔊 PLAYING AUDIO (Bhashini TTS):")
    print(f"           '{text_to_speak}'")

def update_tft_lcd(lcd_text: str):
    """Mock Hardware LCD update via Jetson GPIO/SPI"""
    print("\n[Hardware] 📺 UPDATING 2.8' TFT LCD SCREEN:")
    print(lcd_text)

# =====================================================================
# MAIN PIPELINE ORCHESTRATOR
# =====================================================================
def run_pipeline():
    print("=======================================")
    print(" GRAM SAHAYAK - PIPELINE ORCHESTRATOR")
    print("=======================================\n")
    
    # 1. Initialize the RAG Engine ONCE at startup (This loads the FAISS/CrossEncoder into RAM)
    print("[Pipeline] Booting systems...")
    tutor_engine = GoogleOKFAITutorEngine(jsonl_file="clean_curriculum.jsonl")
    
    # 2. Wait for incoming voice query
    # (Simulated here. In production, this would trigger on a GPIO button press or wake word)
    user_english_query = bhashini_stt_api("simulated_mic_input.wav")
    print(f"[Pipeline] Translated Query: \"{user_english_query}\"")
    
    # 3. Pass the translated query to our RAG Engine
    print("\n[Pipeline] 🧠 Querying AI Tutor RAG Engine...")
    rag_response = tutor_engine.query_tutor(user_english_query)
    
    # 4. Extract standard keys (Because we fixed the dictionary schema, this works 100% of the time!)
    # Whether it's a SUCCESS or a FALLBACK, the engine returns these same fields.
    bhashini_voice = rag_response.get("bhashini_voice_text", "Sorry, error.")
    lcd_display = rag_response.get("tft_lcd_display_card", "Error")
    
    # 5. Output to Jetson Hardware
    update_tft_lcd(lcd_display)
    bhashini_tts_api(bhashini_voice)

if __name__ == "__main__":
    run_pipeline()
