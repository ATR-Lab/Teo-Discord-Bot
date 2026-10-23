import time

from teo.docs import LabDocs


def make_docs():
    docs = LabDocs(session=None)  # type: ignore[arg-type]  # network is never touched below
    docs.index = {'getting-started-atr-lab': ('docs/revamp', ['lab-rules/safety.md'])}
    return docs


async def test_unknown_repo_and_path_are_errors():
    docs = make_docs()
    text, err = await docs.read('nope', 'x.md')
    assert err and 'Unknown repository' in text
    text, err = await docs.read('getting-started-atr-lab', 'secret.md')
    assert err and 'No page' in text


async def test_cached_page_is_returned_with_its_link():
    docs = make_docs()
    docs._cache[('getting-started-atr-lab', 'lab-rules/safety.md')] = (time.time(), '# Safety')
    text, err = await docs.read('getting-started-atr-lab', 'lab-rules/safety.md')
    assert not err
    assert text.startswith(
        'Source: https://github.com/ATR-Lab/getting-started-atr-lab/blob/docs/revamp/'
    )
    assert text.endswith('# Safety')


def test_tool_definition_lists_pages():
    tool = make_docs().tool_definition()
    assert tool['name'] == 'lab_docs'
    assert 'lab-rules/safety.md' in tool['description']
