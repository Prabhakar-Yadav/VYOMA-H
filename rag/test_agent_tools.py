#!/usr/bin/env python3
"""Real agent.run_turn() calls exercising the new G1/G2 tools specifically -- not a
standalone retrieval test (that's rag/test_retrieval.py), this drives the actual
tool-calling loop so we see the agent choose to call these tools, not just that they
work if called directly.

Run: source venv/bin/activate && cd gramsahayak && python3 rag/test_agent_tools.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent"))

from agent import GramSahayakAgent  # noqa: E402

QUERIES = [
    ("G1 disease", "My tomato leaves have brown spots with rings on them, what is it and what should I use?"),
    ("G1 entomology", "There are tiny insects on my chilli leaves causing silvery streaks, what could this be?"),
    ("G2 scheme", "How much money does PM-KISAN give me and how often?"),
    ("G2 eligibility", "I have 2 acres growing tomato in Karnataka, what government schemes could help me?"),
    ("G2 subsidy", "Is there any subsidy for drip irrigation?"),
]


def main():
    agent = GramSahayakAgent()
    results = []
    for label, query in QUERIES:
        print(f"\n{'=' * 90}\n[{label}] {query}\n{'=' * 90}")
        t0 = time.perf_counter()
        messages = agent.run_turn(query, verbose=True)
        elapsed = time.perf_counter() - t0
        tools_called = [
            tc.function.name
            for m in messages
            if getattr(m, "tool_calls", None)
            for tc in m.tool_calls
        ]
        print(f"\ntools called: {tools_called}")
        print(f"turn time: {elapsed:.2f}s")
        print(f"FINAL ANSWER: {messages[-1].content}")
        results.append({"label": label, "query": query, "tools_called": tools_called,
                         "elapsed": elapsed, "answer": messages[-1].content})

    print(f"\n\n{'=' * 90}\nSUMMARY\n{'=' * 90}")
    for r in results:
        print(f"[{r['label']}] tools={r['tools_called']} time={r['elapsed']:.2f}s")


if __name__ == "__main__":
    main()
