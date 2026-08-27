#!/usr/bin/env python3
"""Restore the reference-text technical brief from its Base64 text artifact."""

from __future__ import annotations

import argparse
import base64
import hashlib
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = BASE_DIR / "SRA代理人參考文本與多層全文下載技術說明.docx.b64"
DEFAULT_OUTPUT = BASE_DIR / "SRA代理人參考文本與多層全文下載技術說明.docx"
EXPECTED_SHA256 = "ea08d8bef0498e003c0b6133379234fa10e97f8233767914c87d4560d252f2bc"


def restore_docx(input_path: Path, output_path: Path) -> str:
    """Decode *input_path*, verify the original digest, and write *output_path*."""
    encoded = b"".join(input_path.read_bytes().split())
    restored = base64.b64decode(encoded, validate=True)
    digest = hashlib.sha256(restored).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError(
            f"SHA-256 mismatch: expected {EXPECTED_SHA256}, restored {digest}"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(restored)
    return digest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restore the SRA technical brief DOCX from its Base64 text file."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    digest = restore_docx(args.input, args.output)
    print(f"Restored: {args.output}")
    print(f"SHA-256: {digest} (verified)")


if __name__ == "__main__":
    main()
