"""Read-only access to the lab's public documentation repositories on GitHub.

The index (list of Markdown files) is built once at startup from the GitHub trees API, so the tool
definition stays byte-stable and the prompt cache keeps hitting. File contents come from
raw.githubusercontent.com, which has no API rate limit, and are cached in memory for a few hours.
"""
import asyncio
import logging
import time

import aiohttp

log = logging.getLogger("teo.docs")

ORG = "ATR-Lab"
REPOS = ("about", "getting-started-atr-lab", "dev-guidelines")
# The revamped docs live on docs/revamp until it merges; fall back to the default branch.
BRANCHES = ("docs/revamp", "master", "main")
CACHE_SECONDS = 6 * 3600
MAX_CHARS = 30_000


class LabDocs:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.index: dict[str, tuple[str, list[str]]] = {}  # repo -> (branch, [paths])
        self._cache: dict[tuple[str, str], tuple[float, str]] = {}

    async def load_index(self) -> None:
        for repo in REPOS:
            for branch in BRANCHES:
                url = f"https://api.github.com/repos/{ORG}/{repo}/git/trees/{branch}?recursive=1"
                async with self.session.get(url, headers={"Accept": "application/vnd.github+json"}) as r:
                    if r.status != 200:
                        continue
                    tree = (await r.json()).get("tree", [])
                paths = sorted(t["path"] for t in tree
                               if t["type"] == "blob" and t["path"].endswith(".md")
                               and not t["path"].startswith(".github/") and t["path"] != "CLAUDE.md")
                self.index[repo] = (branch, paths)
                break
            else:
                log.warning("no readable branch for %s", repo)
        log.info("docs index: %s", {r: len(p) for r, (_, p) in self.index.items()})

    def tool_description(self) -> str:
        lines = ["Read a Markdown page from the ATR Lab's public documentation on GitHub. "
                 "Use it before answering questions about lab rules, safety, onboarding, hardware, tooling, "
                 "coding standards, research or the lab's history. Available pages:"]
        for repo in REPOS:
            if repo in self.index:
                lines.append(f"{repo}: " + ", ".join(self.index[repo][1]))
        return "\n".join(lines)

    def tool_definition(self) -> dict:
        return {
            "name": "lab_docs",
            "description": self.tool_description(),
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "enum": list(REPOS)},
                    "path": {"type": "string", "description": "A path from the list, for example lab-rules/safety.md"},
                },
                "required": ["repo", "path"],
                "additionalProperties": False,
            },
        }

    async def read(self, repo: str, path: str) -> tuple[str, bool]:
        """Return (text, is_error)."""
        if repo not in self.index:
            return f"Unknown repository {repo!r}.", True
        branch, paths = self.index[repo]
        if path not in paths:
            return f"No page {path!r} in {repo}. Pick one from the tool description.", True
        key = (repo, path)
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            text = hit[1]
        else:
            url = f"https://raw.githubusercontent.com/{ORG}/{repo}/{branch}/{path}"
            try:
                async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as r:
                    if r.status != 200:
                        return f"GitHub returned HTTP {r.status} for {path}.", True
                    text = await r.text()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                return f"Could not fetch {path}: {e}", True
            self._cache[key] = (time.time(), text)
        link = f"https://github.com/{ORG}/{repo}/blob/{branch}/{path}"
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS] + "\n\n[page truncated]"
        return f"Source: {link}\n\n{text}", False
