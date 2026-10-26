"""Claude side of Teo: one request per Discord turn, with a short tool loop.

Prompt layout for caching: tools, then the system prompt (persona and server map, frozen for the
life of the process), then one user message with the volatile parts (date, channel, recent
conversation, question, attached files). Earlier Discord turns arrive as a plain-text transcript,
so no thinking blocks are replayed across turns; inside one turn, assistant content is appended
unchanged while tools run.

Files Claude cannot read directly are uploaded to the Files API and mounted in the code execution
sandbox for that turn only. Uploads expire after an hour and are deleted as soon as the turn ends.
"""

from dataclasses import dataclass
import logging
import time
from typing import Any, Literal, cast

import anthropic
from anthropic.types.beta import (
    BetaContentBlockParam,
    BetaMessage,
    BetaMessageParam,
    BetaOutputConfigParam,
    BetaTextBlockParam,
    BetaToolResultBlockParam,
    BetaToolUnionParam,
)

from .docs import LabDocs
from .files import Prepared

log = logging.getLogger('teo.brain')

MAX_TOOL_ROUNDS = 8
UPLOAD_TTL_SECONDS = 3600
# Code execution replaces the web tools on turns with sandbox files: the _20260209 web tools run
# their own code environment, and two environments in one request confuse the model.
CODE_EXECUTION: BetaToolUnionParam = {'type': 'code_execution_20260521', 'name': 'code_execution'}
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')
FALLBACK_BETA = 'server-side-fallback-2026-07-01'
REFUSED = (
    "I can't help with that one. If you think I got it wrong, rephrase it or ask a lab member."
)
EMPTY = 'Hmm, my answer came back empty. Mind asking that again?'
TRUNCATED = '\n\n*(I ran out of room there. Ask me to continue.)*'


@dataclass
class Reply:
    """A finished answer plus usage numbers for the log."""

    text: str = ''
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    seconds: float = 0.0
    refused: bool = False


class Brain:
    """Calls Claude with Teo's prompt and tools.

    Args:
        client: Async Anthropic client.
        docs: Lab documentation reader, which backs the `lab_docs` tool.
        system_text: The full system prompt.
        model: Claude model id.
        effort: Effort level (`low`, `medium`, `high`, ...).
        max_tokens: Output cap per request, thinking included.
    """

    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        docs: LabDocs,
        system_text: str,
        model: str,
        effort: str,
        max_tokens: int,
    ) -> None:
        self.client = client
        self.docs = docs
        self.model = model
        if effort not in EFFORTS:
            raise ValueError(f'effort must be one of {EFFORTS}, not {effort!r}')
        effort_level = cast(Literal['low', 'medium', 'high', 'xhigh', 'max'], effort)
        self.output_config: BetaOutputConfigParam = {'effort': effort_level}
        self.max_tokens = max_tokens
        self.system: list[BetaTextBlockParam] = [
            {
                'type': 'text',
                'text': system_text,
                'cache_control': {'type': 'ephemeral', 'ttl': '1h'},
            }
        ]
        self.tools: list[BetaToolUnionParam] = [
            docs.tool_definition(),
            {'type': 'web_search_20260209', 'name': 'web_search', 'max_uses': 3},
            {'type': 'web_fetch_20260209', 'name': 'web_fetch', 'max_uses': 3},
        ]

    def refresh_tools(self) -> None:
        """Rebuild the `lab_docs` tool after the docs index changes (costs one cache write)."""
        self.tools[0] = self.docs.tool_definition()

    async def _create(
        self,
        messages: list[BetaMessageParam],
        tools: list[BetaToolUnionParam],
        container: str | None,
    ) -> BetaMessage:
        return await self.client.beta.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system,
            tools=tools,
            messages=messages,
            output_config=self.output_config,
            betas=[FALLBACK_BETA],
            fallbacks='default',
            container=container or anthropic.omit,
        )

    async def _upload(self, files: list[Prepared]) -> list[str]:
        """Upload sandbox files and return their ids (failed uploads are skipped and logged)."""
        ids: list[str] = []
        for f in files:
            if f.upload is None:
                continue
            try:
                meta = await self.client.files.upload(
                    file=(f.name, f.upload, 'application/octet-stream'),
                    expires_in_seconds=UPLOAD_TTL_SECONDS,
                )
                ids.append(meta.id)
            except anthropic.APIError as e:
                log.warning('file upload failed (%s bytes): %s', len(f.upload), type(e).__name__)
        return ids

    async def _delete(self, ids: list[str]) -> None:
        for file_id in ids:
            try:
                await self.client.files.delete(file_id)
            except anthropic.APIError:
                log.warning('could not delete uploaded file; it expires on its own')

    async def _run_tool(self, name: str, args: Any) -> tuple[str, bool]:
        if name == 'lab_docs' and isinstance(args, dict):
            return await self.docs.read(str(args.get('repo', '')), str(args.get('path', '')))
        return f'Unknown tool {name}.', True

    async def answer(
        self, user_content: str, web: bool = True, files: list[Prepared] | None = None
    ) -> Reply:
        """Answer one Discord turn.

        Args:
            user_content: The turn's context and question, already formatted as text.
            web: Offer web search and web fetch. Off in private research channels; the
                smaller tool list is cached as its own prefix.
            files: Attachments prepared by `teo.files.prepare`. Inline blocks follow the text;
                files that need code are uploaded and mounted in the code execution sandbox.

        Returns:
            The reply text (never empty) and usage numbers.

        Raises:
            anthropic.APIError: When the API call fails after the SDK's own retries.
        """
        start = time.monotonic()
        files = files or []
        uploaded = await self._upload(files)
        try:
            return await self._answer(user_content, web, files, uploaded, start)
        finally:
            await self._delete(uploaded)

    async def _answer(
        self,
        user_content: str,
        web: bool,
        files: list[Prepared],
        uploaded: list[str],
        start: float,
    ) -> Reply:
        content: list[BetaContentBlockParam] = [{'type': 'text', 'text': user_content}]
        for f in files:
            content += f.blocks
        content += [{'type': 'container_upload', 'file_id': i} for i in uploaded]
        messages: list[BetaMessageParam] = [{'role': 'user', 'content': content}]
        if uploaded:
            tools = [self.tools[0], CODE_EXECUTION]
        else:
            tools = self.tools if web else self.tools[:1]
        reply = Reply()
        response: BetaMessage | None = None
        container: str | None = None
        for _ in range(MAX_TOOL_ROUNDS):
            response = await self._create(messages, tools, container)
            if response.container is not None:
                container = response.container.id  # keep the sandbox (and its files) this turn
            u = response.usage
            reply.input_tokens += u.input_tokens
            reply.output_tokens += u.output_tokens
            reply.cache_read += u.cache_read_input_tokens or 0
            reply.cache_write += u.cache_creation_input_tokens or 0

            if response.stop_reason == 'refusal':
                reply.refused = True
                break
            if response.stop_reason == 'pause_turn':
                messages.append({'role': 'assistant', 'content': response.content})
                continue
            if response.stop_reason != 'tool_use':
                break

            messages.append({'role': 'assistant', 'content': response.content})
            results: list[BetaToolResultBlockParam] = []
            for block in response.content:
                if block.type == 'tool_use':
                    text, is_error = await self._run_tool(block.name, block.input)
                    results.append(
                        {
                            'type': 'tool_result',
                            'tool_use_id': block.id,
                            'content': text,
                            'is_error': is_error,
                        }
                    )
            messages.append({'role': 'user', 'content': results})

        reply.seconds = time.monotonic() - start
        if reply.refused:
            reply.text = REFUSED
        elif response is not None:
            reply.text = ''.join(b.text for b in response.content if b.type == 'text').strip()
            if reply.text and response.stop_reason == 'max_tokens':
                reply.text += TRUNCATED
        reply.text = reply.text or EMPTY
        return reply
