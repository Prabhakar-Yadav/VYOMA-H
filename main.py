import sys
from ai_tutor_rag import GoogleOKFAITutorEngine

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

if __name__ == "__main__":
    tutor = GoogleOKFAITutorEngine()
    
    test_questions = [
        "How do plants make food using sunlight?",
        "What is Arithmetic Progression? Give daily life examples",
        "How to purify drinking water in villages?"
    ]
    
    for question in test_questions:
        res = tutor.query_tutor(question, dialect="Bhojpuri")
        print("\n=========================================================")
        print(f"QUERY: \"{res['question']}\"")
        print(f"TOP MATCH: {res['top_match']['doc_id']} (Score: {res['top_match']['similarity_score']})")
        print(f"TOPIC: {res['top_match']['topic']}")
        print(f"\nEXPLANATION:\n{res['explanation_text']}")
        print(f"\nLATENCY: {res['latency_seconds']}s")
        print("=========================================================")
