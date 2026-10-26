from types import SimpleNamespace

import pytest

from teo.brain import EMPTY, REFUSED, Brain


def usage():
    return SimpleNamespace(
        input_tokens=10,
        output_tokens=5,
        cache_read_input_tokens=100,
        cache_creation_input_tokens=0,
    )


def message(stop, *blocks):
    return SimpleNamespace(stop_reason=stop, content=list(blocks), usage=usage(), container=None)


def text(t):
    return SimpleNamespace(type='text', text=t)


def tool_use(name, args):
    return SimpleNamespace(type='tool_use', id='tu_1', name=name, input=args)


class FakeDocs:
    def __init__(self):
        self.reads = []

    def tool_definition(self):
        return {'name': 'lab_docs', 'description': 'docs', 'input_schema': {'type': 'object'}}

    async def read(self, repo, path):
        self.reads.append((repo, path))
        return f'page {path}', False


class FakeClient:
    def __init__(self, responses):
        self.calls = []
        self._responses = iter(responses)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        return next(self._responses)


def brain(responses, docs=None):
    client = FakeClient(responses)
    return Brain(client, docs or FakeDocs(), 'system', 'claude-opus-5-5', 'low', 1000), client


async def test_plain_answer():
    b, client = brain([message('end_turn', text('Hello there'))])
    reply = await b.answer('hi')
    assert reply.text == 'Hello there'
    assert reply.cache_read == 100
    call = client.calls[0]
    assert call['fallbacks'] == 'default'
    assert call['output_config'] == {'effort': 'low'}
    assert call['system'][0]['cache_control']['ttl'] == '1h'


async def test_tool_loop_reads_docs_then_answers():
    docs = FakeDocs()
    b, client = brain(
        [
            message('tool_use', tool_use('lab_docs', {'repo': 'about', 'path': 'research.md'})),
            message('end_turn', text('Done')),
        ],
        docs,
    )
    reply = await b.answer('what does the lab research?')
    assert reply.text == 'Done'
    assert docs.reads == [('about', 'research.md')]
    second = client.calls[1]['messages']
    assert second[1]['role'] == 'assistant'
    assert second[2]['content'][0]['type'] == 'tool_result'
    assert second[2]['content'][0]['content'] == 'page research.md'
    assert reply.input_tokens == 20


async def test_refusal_gets_a_friendly_message():
    b, _ = brain([message('refusal')])
    reply = await b.answer('x')
    assert reply.refused
    assert reply.text == REFUSED


async def test_empty_answer_falls_back():
    b, _ = brain([message('end_turn')])
    assert (await b.answer('x')).text == EMPTY


def test_bad_effort_is_rejected():
    with pytest.raises(ValueError):
        Brain(FakeClient([]), FakeDocs(), 's', 'm', 'turbo', 10)


async def test_web_tools_can_be_turned_off():
    b, client = brain([message('end_turn', text('ok')), message('end_turn', text('ok'))])
    await b.answer('x', web=False)
    await b.answer('y')
    assert [t['name'] for t in client.calls[0]['tools']] == ['lab_docs']
    assert [t['name'] for t in client.calls[1]['tools']] == ['lab_docs', 'web_search', 'web_fetch']


class FakeFiles:
    def __init__(self):
        self.uploaded, self.deleted = [], []

    async def upload(self, file, expires_in_seconds):
        self.uploaded.append((file[0], expires_in_seconds))
        return SimpleNamespace(id=f'file_{len(self.uploaded)}')

    async def delete(self, file_id):
        self.deleted.append(file_id)


async def test_sandbox_files_are_uploaded_mounted_and_deleted():
    from teo.files import prepare

    b, client = brain([message('end_turn', text('It is a Word file'))])
    client.files = FakeFiles()
    docx = prepare('report.docx', None, b'PK\x03\x04\x00\x00binary')
    note = prepare('notes.md', None, b'# hi')
    reply = await b.answer('what is in these?', files=[docx, note])
    assert reply.text == 'It is a Word file'
    call = client.calls[0]
    assert [t['name'] for t in call['tools']] == ['lab_docs', 'code_execution']
    content = call['messages'][0]['content']
    assert content[0]['type'] == 'text'
    assert content[1]['type'] == 'document'  # notes.md inline
    assert content[2] == {'type': 'container_upload', 'file_id': 'file_1'}
    assert client.files.uploaded == [('report.docx', 3600)]
    assert client.files.deleted == ['file_1']


async def test_files_are_deleted_even_when_the_api_fails():
    from teo.files import prepare

    class Boom(FakeClient):
        async def _create(self, **kwargs):
            raise RuntimeError('api down')

    client = Boom([])
    client.files = FakeFiles()
    b = Brain(client, FakeDocs(), 's', 'claude-opus-5-5', 'low', 10)
    with pytest.raises(RuntimeError):
        await b.answer('x', files=[prepare('a.bin', None, b'\x00\x01')])
    assert client.files.deleted == ['file_1']
