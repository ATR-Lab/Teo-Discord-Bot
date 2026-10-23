"""Read-only access to the lab's public documentation repositories on GitHub.

The index (the list of Markdown pages) is built at startup from the GitHub trees API, so the tool
definition stays byte-stable and the prompt cache keeps hitting. Page contents come from
raw.githubusercontent.com, which has no API rate limit, and are cached in memory for six hours.
"""

import logging
import time

import aiohttp
from anthropic.types.beta import BetaToolParam

log = logging.getLogger('teo.docs')

ORG = 'ATR-Lab'
REPOS = ('about', 'getting-started-atr-lab', 'dev-guidelines')
# The revamped docs live on docs/revamp until it merges; then the default branch takes over.
BRANCHES = ('docs/revamp', 'master', 'main')
CACHE_SECONDS = 6 * 3600
MAX_CHARS = 30_000


class LabDocs:
    """Index and cached reader for the lab's documentation repositories.

    Args:
        session: Shared HTTP session.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.session = session
        self.index: dict[str, tuple[str, list[str]]] = {}  # repo -> (branch, paths)
        self._cache: dict[tuple[str, str], tuple[float, str]] = {}

    async def load_index(self) -> None:
        """List the Markdown pages of each repository, from the first branch that exists."""
        for repo in REPOS:
            for branch in BRANCHES:
                url = f'https://api.github.com/repos/{ORG}/{repo}/git/trees/{branch}?recursive=1'
                headers = {'Accept': 'application/vnd.github+json'}
                async with self.session.get(url, headers=headers) as r:
                    if r.status != 200:
                        continue
                    tree = (await r.json()).get('tree', [])
                self.index[repo] = (
                    branch,
                    sorted(
                        t['path']
                        for t in tree
                        if t['type'] == 'blob'
                        and t['path'].endswith('.md')
                        and not t['path'].startswith('.github/')
                        and t['path'] != 'CLAUDE.md'
                    ),
                )
                break
            else:
                log.warning('no readable branch for %s', repo)
        log.info('docs index: %s', {r: len(p) for r, (_, p) in self.index.items()})

    def tool_definition(self) -> BetaToolParam:
        """Return the `lab_docs` tool, whose description lists every page in the index."""
        lines = [
            "Read a Markdown page from the ATR Lab's public documentation on GitHub. Use it "
            'before answering questions about lab rules, safety, onboarding, hardware, tooling, '
            "coding standards, research or the lab's history. Available pages:"
        ]
        lines += [
            f'{repo}: ' + ', '.join(self.index[repo][1]) for repo in REPOS if repo in self.index
        ]
        return {
            'name': 'lab_docs',
            'description': '\n'.join(lines),
            'strict': True,
            'input_schema': {
                'type': 'object',
                'properties': {
                    'repo': {'type': 'string', 'enum': list(REPOS)},
                    'path': {
                        'type': 'string',
                        'description': 'A path from the list, for example lab-rules/safety.md',
                    },
                },
                'required': ['repo', 'path'],
                'additionalProperties': False,
            },
        }

    async def read(self, repo: str, path: str) -> tuple[str, bool]:
        """Fetch one page.

        Args:
            repo: One of `REPOS`.
            path: A path listed in the index for that repository.

        Returns:
            The page text, prefixed with its GitHub link, and whether this is an error message.
        """
        if repo not in self.index:
            return f'Unknown repository {repo!r}.', True
        branch, paths = self.index[repo]
        if path not in paths:
            return f'No page {path!r} in {repo}. Pick one from the tool description.', True
        hit = self._cache.get((repo, path))
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            text = hit[1]
        else:
            url = f'https://raw.githubusercontent.com/{ORG}/{repo}/{branch}/{path}'
            try:
                timeout = aiohttp.ClientTimeout(total=20)
                async with self.session.get(url, timeout=timeout) as r:
                    if r.status != 200:
                        return f'GitHub returned HTTP {r.status} for {path}.', True
                    text = await r.text()
            except (TimeoutError, aiohttp.ClientError) as e:
                return f'Could not fetch {path}: {e}', True
            self._cache[(repo, path)] = (time.time(), text)
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS] + '\n\n[page truncated]'
        return f'Source: https://github.com/{ORG}/{repo}/blob/{branch}/{path}\n\n{text}', False
