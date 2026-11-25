"""Build one standalone admin-importable Pipe from exact canonical modules.

No dependency installation, deployment, secret or network IO. Output is
explicit; an existing file is never overwritten. Keep signing and transport
source shared rather than maintaining a second implementation.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    "sra_api/security/sraf_handoff_assertion.py",
    "sra_api/security/sraf_handoff_transport.py",
    "integrations/openwebui/sraf_backend_pipe.py",
)
_ALLOWED = frozenset(("api.security.sraf_handoff_assertion",
                      "api.security.sraf_handoff_transport"))
_HEADER = '''"""
title: SRAF verified backend report
author: SRAF
version: 0.2.0
description: OpenWebUI 0.13.4 saved-root pilot; backend signing, no personal token.
"""
from __future__ import annotations
'''


def build(root=ROOT):
    chunks = [_HEADER]
    for relative in SOURCES:
        raw = (root / relative).read_text(encoding="utf-8")
        tree = ast.parse(raw)
        lines = raw.splitlines(keepends=True)
        remove = set()
        for i, node in enumerate(tree.body):
            skip = (i == 0 and isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str))
            if isinstance(node, ast.ImportFrom):
                if node.module == "__future__" or node.module in _ALLOWED:
                    skip = True
                elif node.module and node.module.startswith(("api.", "sra_api.")):
                    raise ValueError("unsupported_server_import")
            if skip:
                remove.update(range(node.lineno, node.end_lineno + 1))
        chunks.append("\n# Canonical source: " + relative + "\n")
        chunks.append("".join(line for n, line in enumerate(lines, 1) if n not in remove))
        chunks.append("\n")
    output = "".join(chunks)
    compile(output, "sraf_backend_pipe_bundle.py", "exec")
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    with args.output.open("x", encoding="utf-8", newline="\n") as out:
        out.write(build())
    print("PIPE_BUNDLE_CREATED")


if __name__ == "__main__":
    main()
