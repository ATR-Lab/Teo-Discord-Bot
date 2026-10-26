"""Turn Discord attachments into something Claude can read.

Four routes, picked per file:

- **text**: anything that decodes as UTF-8 (code, logs, Markdown, CSV, JSON, URDF, notebooks and
  Discord's own `message.txt` for long pastes) goes inline as a text document. Very long text
  keeps its start and end, where errors usually are, and the whole file also goes to the sandbox.
- **image**: PNG, JPEG, GIF and WebP go inline as images, downscaled for the API.
- **pdf**: PDFs go inline as documents; Claude reads them natively.
- **sandbox**: everything else (Office files, archives, NumPy, ROS bags, HEIC and so on) is
  uploaded to Claude's code execution sandbox, where Claude writes code to open it.
"""

import base64
from dataclasses import dataclass, field
import io
from pathlib import PurePath
from typing import Literal

from anthropic.types.beta import BetaContentBlockParam, BetaImageBlockParam
from PIL import Image, UnidentifiedImageError

Kind = Literal['text', 'image', 'pdf', 'sandbox', 'skip']

MAX_FILES = 6
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 40 * 1024 * 1024
INLINE_TEXT_CHARS = 120_000  # about 30,000 tokens; longer text is excerpted inline
EXCERPT_HEAD = 20_000
EXCERPT_TAIL = 60_000
INLINE_PDF_BYTES = 20 * 1024 * 1024
IMAGE_MAX_EDGE = 1568  # the long edge Claude reads at full detail
IMAGE_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
               '.gif': 'image/gif', '.webp': 'image/webp'}  # fmt: skip


@dataclass
class Prepared:
    """One attachment, ready for the request.

    Attributes:
        name: The file name as posted.
        kind: The route the file takes.
        blocks: Content blocks to place in the user turn (empty for sandbox-only files).
        upload: Bytes to upload to the code execution sandbox, if any.
        note: One line for the transcript describing what Claude receives.
    """

    name: str
    kind: Kind
    blocks: list[BetaContentBlockParam] = field(default_factory=list)
    upload: bytes | None = None
    note: str = ''


def decode_text(data: bytes) -> str | None:
    """Return the text if the bytes look like a text file, else None."""
    if b'\x00' in data[:8192] and not data.startswith((b'\xff\xfe', b'\xfe\xff')):
        return None
    for encoding in ('utf-8-sig', 'utf-16'):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if encoding == 'utf-16' and not data.startswith((b'\xff\xfe', b'\xfe\xff')):
            return None  # only trust UTF-16 when it says so
        return text
    return None


def excerpt(text: str) -> str:
    """Keep the start and the end of a long text, marking the cut."""
    if len(text) <= INLINE_TEXT_CHARS:
        return text
    cut = len(text) - EXCERPT_HEAD - EXCERPT_TAIL
    return (
        f'{text[:EXCERPT_HEAD]}\n\n[... {cut:,} characters omitted here; the full file is in '
        f'your code execution sandbox ...]\n\n{text[-EXCERPT_TAIL:]}'
    )


ImageMedia = Literal['image/png', 'image/jpeg']


def shrink_image(data: bytes) -> tuple[bytes, ImageMedia] | None:
    """Downscale an image so its long edge is at most IMAGE_MAX_EDGE.

    Returns:
        The encoded bytes and media type, or None if Pillow cannot open the file.
    """
    try:
        im = Image.open(io.BytesIO(data))
        im.seek(0)  # first frame of an animation
        im.load()
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    im.thumbnail((IMAGE_MAX_EDGE, IMAGE_MAX_EDGE))
    out = io.BytesIO()
    if im.mode in ('RGBA', 'LA', 'P'):
        im.convert('RGBA').save(out, 'PNG', optimize=True)
        return out.getvalue(), 'image/png'
    im.convert('RGB').save(out, 'JPEG', quality=85)
    return out.getvalue(), 'image/jpeg'


def classify(name: str, content_type: str | None, data: bytes) -> Kind:
    """Pick the route for one file from its name, declared type and bytes."""
    suffix = PurePath(name).suffix.lower()
    ctype = (content_type or '').split(';')[0].strip().lower()
    if suffix in IMAGE_TYPES or (ctype.startswith('image/') and ctype != 'image/svg+xml'):
        return 'image'  # prepare() falls back to the sandbox if Pillow can't open it
    if ctype.startswith(('audio/', 'video/')):
        return 'sandbox'
    if suffix == '.pdf' or ctype == 'application/pdf':
        return 'pdf' if len(data) <= INLINE_PDF_BYTES else 'sandbox'
    if decode_text(data) is not None:
        return 'text'
    return 'sandbox'


def prepare(name: str, content_type: str | None, data: bytes) -> Prepared:
    """Build the request pieces for one attachment."""
    kind = classify(name, content_type, data)
    if kind == 'image':
        shrunk = shrink_image(data)
        if shrunk is None:  # an image type Pillow can't open (for example HEIC): try code
            return prepare_sandbox(name, data)
        img, media = shrunk
        block: BetaImageBlockParam = {
            'type': 'image',
            'source': {'type': 'base64', 'media_type': media, 'data': _b64(img)},
        }
        return Prepared(name, 'image', [block], note=f'{name} (image, shown to you below)')
    if kind == 'pdf':
        doc: BetaContentBlockParam = {
            'type': 'document',
            'title': name,
            'source': {'type': 'base64', 'media_type': 'application/pdf', 'data': _b64(data)},
        }
        return Prepared(name, 'pdf', [doc], note=f'{name} (PDF, attached below)')
    if kind == 'text':
        text = decode_text(data) or ''
        long = len(text) > INLINE_TEXT_CHARS
        doc = {
            'type': 'document',
            'title': name,
            'source': {'type': 'text', 'media_type': 'text/plain', 'data': excerpt(text)},
        }
        return Prepared(
            name,
            'text',
            [doc],
            upload=data if long else None,
            note=f'{name} ({len(text):,} characters'
            + (', excerpt below, full file in your code sandbox)' if long else ', below)'),
        )
    return prepare_sandbox(name, data)


def prepare_sandbox(name: str, data: bytes) -> Prepared:
    """Send a file to the code execution sandbox only."""
    return Prepared(
        name,
        'sandbox',
        upload=data,
        note=f'{name} ({len(data):,} bytes, not readable directly: it is in your code '
        'execution sandbox, open it with code)',
    )


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')
