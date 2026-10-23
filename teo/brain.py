"""Claude side of Teo: one request per Discord turn, with a short tool loop.

Prompt layout for caching: tools -> system (persona + server map, frozen for the process) -> one user
message holding the volatile parts (date, channel, recent conversation, the question). Prior Discord
turns are passed as a plain-text transcript, so no thinking blocks are ever replayed across turns; inside
one turn the assistant content is appended unchanged while tools run.
"""
import json
import logging
import time
from dataclasses import dataclass

import anthropic

from .docs import LabDocs

log = logging.getLogger("teo.brain")

MAX_TOOL_ROUNDS = 6
FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class Reply:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    seconds: float = 0.0
    refused: bool = False


class Brain:
    def __init__(self, client: anthropic.AsyncAnthropic, docs: LabDocs, system_text: str,
                 model: str, effort: str, max_tokens: int):
        self.client = client
        self.docs = docs
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.system = [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
        self.tools = [
            docs.tool_definition(),
            {"type": "web_search_20260209", "name": "web_search", "max_uses": 3},
            {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 3},
        ]

    def refresh_tools(self) -> None:
        self.tools[0] = self.docs.tool_definition()

    async def answer(self, user_content: str) -> Reply:
        start = time.monotonic()
        messages: list[dict] = [{"role": "user", "content": user_content}]
        totals = Reply(text="")
        response = None
        for _ in range(MAX_TOOL_ROUNDS):
            response = await self.client.beta.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.system,
                tools=self.tools,
                messages=messages,
                output_config={"effort": self.effort},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
            u = response.usage
            totals.input_tokens += u.input_tokens
            totals.output_tokens += u.output_tokens
            totals.cache_read += u.cache_read_input_tokens or 0
            totals.cache_write += u.cache_creation_input_tokens or 0

            if response.stop_reason == "refusal":
                totals.refused = True
                break
            if response.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": response.content})
                continue
            if response.stop_reason != "tool_use":
                break

            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if block.name == "lab_docs":
                    args = block.input if isinstance(block.input, dict) else json.loads(block.input)
                    text, is_error = await self.docs.read(args.get("repo", ""), args.get("path", ""))
                else:
                    text, is_error = f"Unknown tool {block.name}.", True
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": text, "is_error": is_error})
            messages.append({"role": "user", "content": results})

        totals.seconds = time.monotonic() - start
        if totals.refused:
            totals.text = ("I can't help with that one. If you think I got it wrong, try rephrasing, "
                           "or ask a lab member.")
        elif response is not None:
            totals.text = "".join(b.text for b in response.content if b.type == "text").strip()
            if response.stop_reason == "max_tokens":
                totals.text += "\n\n*(I ran out of room there. Ask me to continue.)*"
        if not totals.text:
            totals.text = "Hmm, my answer came back empty. Mind asking that again?"
        return totals
