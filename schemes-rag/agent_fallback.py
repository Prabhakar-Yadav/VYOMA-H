"""
Agent Tool-Calling Fallback & Empty Response Synthesis Engine.
Fixes recursive tool loops and empty response ("") failure modes in compact local LLMs
(e.g., LFM2.5-VL-3B, Qwen2.5-3B, Gemma-2-2B) on NVIDIA Jetson.
"""
import json
import logging
from typing import Any, Callable, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Agent_Fallback")


class SafeAgentExecutor:
    """
    Guarantees that an agent will never return an empty response or enter infinite tool loops.
    """
    def __init__(
        self,
        llm_client: Any,
        model_name: str = "lfm2.5-vl-3b",
        max_tool_iterations: int = 4,
    ):
        self.client = llm_client
        self.model_name = model_name
        self.max_iterations = max_tool_iterations

    def execute_with_fallback(
        self,
        messages: List[Dict[str, str]],
        available_tools: List[Dict[str, Any]],
        tool_dispatch_fn: Callable[[str, Dict[str, Any]], str],
        system_instructions: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Runs the tool calling loop. If the model exhausts its iteration budget or fails
        to synthesize a textual reply, strips tools and forces final direct synthesis.
        """
        conversation = list(messages)
        accumulated_observations = []
        iteration = 0

        while iteration < self.max_iterations:
            iteration += 1
            try:
                response = self.client.chat(
                    model=self.model_name,
                    messages=conversation,
                    tools=available_tools if available_tools else None,
                    options={"temperature": 0.1, "top_p": 0.9},
                )
            except Exception as e:
                logger.error(f"LLM call failed at iteration {iteration}: {e}")
                break

            msg = response.get("message", {})
            content = msg.get("content", "") or ""
            tool_calls = msg.get("tool_calls", [])

            # If the model produced a non-empty text response and no tool calls, return immediately
            if content.strip() and not tool_calls:
                return {
                    "status": "success",
                    "response": content.strip(),
                    "iterations": iteration,
                    "tool_observations": accumulated_observations,
                    "fallback_triggered": False,
                }

            # If tool calls are requested, execute them
            if tool_calls:
                conversation.append(msg)
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    fn_name = fn.get("name", "")
                    fn_args = fn.get("arguments", {})
                    if isinstance(fn_args, str):
                        try:
                            fn_args = json.loads(fn_args)
                        except Exception:
                            fn_args = {}

                    logger.info(f"Dispatching tool '{fn_name}' with args {fn_args}")
                    tool_result = tool_dispatch_fn(fn_name, fn_args)
                    accumulated_observations.append({
                        "tool": fn_name,
                        "args": fn_args,
                        "result": tool_result,
                    })

                    conversation.append({
                        "role": "tool",
                        "content": str(tool_result),
                        "name": fn_name,
                    })
            else:
                # Model returned empty text and no tools -> break to forced synthesis
                logger.warning(f"Iteration {iteration}: Model returned empty response. Triggering fallback.")
                break

        # FALLBACK SYNTHESIS: Iteration budget exceeded or empty response encountered
        logger.info("Triggering Forced Final Synthesis Fallback...")
        return self._force_final_synthesis(conversation, accumulated_observations, system_instructions)

    def _force_final_synthesis(
        self,
        conversation: List[Dict[str, str]],
        observations: List[Dict[str, Any]],
        system_instructions: Optional[str],
    ) -> Dict[str, Any]:
        """
        Strips all tool schemas and prompts the model to summarize the observations into a
        farmer-friendly answer. If that still produces empty string, uses rule-based synthesis.
        """
        obs_text = "\n\n".join([
            f"Tool '{o['tool']}' Output:\n{o['result']}" for o in observations
        ])

        synthesis_prompt = (
            "You are Gram Sahayak, a helpful assistant for rural Indian farmers.\n"
            "Based on the following retrieved information, provide a direct, clear, and helpful response "
            "answering the user's question. DO NOT call any more tools.\n\n"
            f"=== RETRIEVED INFORMATION ===\n{obs_text}\n\n"
            "Farmer-Friendly Response:"
        )

        forced_messages = [
            {"role": "system", "content": synthesis_prompt},
            {"role": "user", "content": conversation[0].get("content", "")},
        ]

        try:
            fallback_response = self.client.chat(
                model=self.model_name,
                messages=forced_messages,
                tools=None,  # STRICTLY NULL TOOLS
                options={"temperature": 0.2, "top_p": 0.9},
            )
            final_text = fallback_response.get("message", {}).get("content", "").strip()
            if final_text:
                return {
                    "status": "success",
                    "response": final_text,
                    "iterations": self.max_iterations,
                    "tool_observations": observations,
                    "fallback_triggered": True,
                }
        except Exception as e:
            logger.error(f"Fallback synthesis LLM call failed: {e}")

        # Deterministic Rule-Based Fallback (Zero Hallucination Guarantee)
        if observations:
            rule_based_reply = f"Here is the verified information for your request:\n\n{observations[-1]['result']}"
        else:
            rule_based_reply = (
                "I could not retrieve the scheme details at this moment. "
                "Please ask your question with the specific scheme name or visit your nearest Gram Panchayat / CSC centre."
            )

        return {
            "status": "fallback_deterministic",
            "response": rule_based_reply,
            "iterations": self.max_iterations,
            "tool_observations": observations,
            "fallback_triggered": True,
        }
