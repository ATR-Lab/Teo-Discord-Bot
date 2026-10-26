import base64
import io

from PIL import Image

from teo.files import (
    EXCERPT_HEAD,
    EXCERPT_TAIL,
    INLINE_TEXT_CHARS,
    classify,
    decode_text,
    excerpt,
    prepare,
)


def png(w, h, mode='RGB'):
    b = io.BytesIO()
    Image.new(mode, (w, h), 'navy').save(b, 'PNG')
    return b.getvalue()


def test_discord_message_txt_is_text():
    data = b'Requirement already satisfied: numpy==2.5.4\nERROR: build failed\n'
    p = prepare('message.txt', 'text/plain; charset=utf-8', data)
    assert p.kind == 'text'
    assert p.upload is None
    assert p.blocks[0]['source']['data'].endswith('build failed\n')


def test_code_and_config_without_content_type_are_text():
    for name in (
        'node.py',
        'robot.urdf',
        'params.yaml',
        'notes.md',
        'launch.launch.py',
        'x.ipynb',
    ):
        assert classify(name, None, b'print(1)\n') == 'text'


def test_binary_goes_to_the_sandbox():
    data = b'PK\x03\x04' + bytes(range(256)) * 4  # a zip/docx-like header with NUL bytes
    p = prepare('report.docx', None, data)
    assert p.kind == 'sandbox'
    assert p.upload == data
    assert p.blocks == []
    assert 'sandbox' in p.note


def test_long_text_is_excerpted_and_uploaded_whole():
    text = 'line\n' * (INLINE_TEXT_CHARS // 4)
    p = prepare('build.log', 'text/plain', text.encode())
    inline = p.blocks[0]['source']['data']
    assert len(inline) < len(text)
    assert 'characters omitted' in inline
    assert p.upload == text.encode()
    assert len(excerpt(text)) <= EXCERPT_HEAD + EXCERPT_TAIL + 200


def test_large_image_is_downscaled():
    p = prepare('photo.png', 'image/png', png(4000, 2000))
    assert p.kind == 'image'
    src = p.blocks[0]['source']
    im = Image.open(io.BytesIO(base64.b64decode(src['data'])))
    assert max(im.size) == 1568
    assert src['media_type'] == 'image/jpeg'


def test_transparent_image_stays_png():
    p = prepare('icon.png', 'image/png', png(64, 64, 'RGBA'))
    assert p.blocks[0]['source']['media_type'] == 'image/png'


def test_unopenable_image_falls_back_to_sandbox():
    p = prepare('photo.heic', 'image/heic', b'not really an image')
    assert p.kind == 'sandbox'


def test_pdf_is_a_document():
    p = prepare('paper.pdf', 'application/pdf', b'%PDF-1.7 fake')
    assert p.kind == 'pdf'
    assert p.blocks[0]['source']['media_type'] == 'application/pdf'


def test_decode_text_rejects_binary_and_accepts_utf16_with_bom():
    assert decode_text(b'\x00\x01\x02') is None
    assert decode_text('héllo'.encode('utf-16')) == 'héllo'
