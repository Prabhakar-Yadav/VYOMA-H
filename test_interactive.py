import sys
import os

from government_schemes_rag import GovernmentSchemesRAGEngine
from test_tencent_agent_memory import TencentAgentMemoryHub

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

def interactive_test():
    print("=========================================================")
    print("🌾 GRAM SAHAYAK - LIVE INTERACTIVE RAG TESTER")
    print("=========================================================")
    print("Loading RAG Engines... Please wait a few seconds.\n")
    
    govt_engine = GovernmentSchemesRAGEngine()
    tencent_memory = TencentAgentMemoryHub()
    
    print("\n✅ RAG Engines Ready!")
    print("Type your question below (or type 'exit' or 'q' to quit).\n")
    
    while True:
        try:
            user_input = input("\n👉 Enter Farmer Question: ").strip()
            if not user_input or user_input.lower() in ['exit', 'q', 'quit']:
                print("Exiting interactive test. Bye!")
                break
                
            print(f"\n🔍 Searching for: \"{user_input}\"...")
            res = govt_engine.query_schemes(user_input)
            
            print("---------------------------------------------------------")
            print(f"STATUS         : {res['status'].upper()}")
            if res['status'] == 'success':
                print(f"SCHEME MATCHED : {res['scheme_name']} ({res['scheme_id']})")
                print(f"CONFIDENCE     : {res['confidence_score']}")
                print(f"RELEVANT ANSWER:\n{res['answer']}\n")
                print(f"VOICE TEXT (Bhashini TTS):\n{res['voice_text']}\n")
                print(f"LCD TEXT (2.8\" Screen):\n{res['lcd_text']}")
            else:
                print(f"CONFIDENCE     : {res['confidence_score']} (Below Cutoff)")
                print(f"VOICE TEXT     : {res['voice_text']}")
            print(f"LATENCY        : {res['latency_ms']} ms")
            print("---------------------------------------------------------")
            
        except KeyboardInterrupt:
            print("\nExiting interactive test. Bye!")
            break
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    interactive_test()
