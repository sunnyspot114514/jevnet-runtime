from __future__ import annotations

import hashlib
from pathlib import Path


def frozen_text_sha256(path: str | Path) -> str:
    """Hash frozen text artifacts using the historical CRLF byte form.

    Several early experiment artifacts were frozen on Windows before the
    repository adopted LF-normalized Git checkouts. Their published SHA-256
    values therefore include CRLF line endings. Normalize any checkout to that
    historical representation so integrity checks are platform-independent
    without changing the frozen files or their published hashes.
    """
    data = Path(path).read_bytes()
    data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    canonical = data.replace(b"\n", b"\r\n")
    return hashlib.sha256(canonical).hexdigest()
