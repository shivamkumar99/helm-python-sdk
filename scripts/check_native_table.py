#!/usr/bin/env python3
"""Verify the ctypes declaration table matches helm_c.h.

A mistyped signature in ``_native.py`` corrupts memory at runtime rather than
failing loudly, so CI diffs the table against the real header on every run.

Usage:
    python scripts/check_native_table.py path/to/helm_c.h
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

# Read the table without importing anything: the module source is parsed as
# an AST, so neither the native library nor any Python code is loaded.
_native_source = (
    Path(__file__).resolve().parents[1] / "src" / "helm_python" / "_native.py"
).read_text()

# C declaration -> canonical type name, longest patterns first.
_C_TYPES: list[tuple[str, str]] = [
    ("const char *", "str_in"),
    ("const char*", "str_in"),
    ("char **", "str_out"),
    ("char**", "str_out"),
    # A bare `char*` — returned by the library, or handed back to
    # helm_free_string — is an OWNED pointer: ctypes must see a void pointer
    # so the address survives (c_char_p would copy and lose it).
    ("char *", "void_p"),
    ("char*", "void_p"),
    ("helm_handle_t *", "handle_out"),
    ("helm_handle_t*", "handle_out"),
    ("helm_handle_t", "handle"),
    ("const uint8_t *", "bytes_in"),
    ("const uint8_t*", "bytes_in"),
    # helm_handle_t is a uint64_t typedef; ctypes sees one c_uint64 type for
    # both, so a bare uint64_t canonicalizes the same way.
    ("uint64_t", "handle"),
    ("helm_log_callback", "log_cb"),
    ("void *", "void_p"),
    ("void*", "void_p"),
    ("int32_t", "i32"),
    ("int64_t", "i64"),
    ("void", "void"),
]

# ctypes expression (as unparsed source, aliases resolved) -> canonical name.
_PY_TYPES: dict[str, str] = {
    "ctypes.POINTER(ctypes.c_uint8)": "bytes_in",
    "ctypes.c_char_p": "str_in",
    "ctypes.POINTER(ctypes.c_void_p)": "str_out",
    "ctypes.c_void_p": "void_p",
    "ctypes.POINTER(ctypes.c_uint64)": "handle_out",
    "ctypes.c_uint64": "handle",
    "ctypes.c_int32": "i32",
    "ctypes.c_int64": "i64",
    "None": "void",
}

_DECL = re.compile(
    r"^(int32_t|int64_t|char\s*\*|void)\s+(helm_[a-z_0-9]+)\s*\(([^;]*?)\)\s*;",
    re.MULTILINE | re.DOTALL,
)


def _canon_c(decl: str) -> str:
    decl = " ".join(decl.split()).replace(" ,", ",")
    # strip the parameter name, keeping the type
    for c_type, canon in _C_TYPES:
        if decl.startswith(c_type):
            return canon
    raise SystemExit(f"check_native_table: unrecognized C type in {decl!r}")


def parse_header(path: Path) -> dict[str, tuple[str, list[str]]]:
    text = path.read_text()
    # Drop comments so declarations inside them are not picked up.
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)

    out: dict[str, tuple[str, list[str]]] = {}
    for restype, name, params in _DECL.findall(text):
        ret = _canon_c(restype.strip())
        params = " ".join(params.split())
        args: list[str] = []
        if params and params != "void":
            args = [_canon_c(p.strip()) for p in params.split(",")]
        out[name] = (ret, args)
    return out


def _canon_py(expr: ast.expr, aliases: dict[str, str]) -> str:
    """Canonicalize a declaration-table type expression via the alias map."""
    text = ast.unparse(expr)
    seen: set[str] = set()
    while text in aliases and text not in seen:
        if text == "LOG_CALLBACK":
            return "log_cb"
        seen.add(text)
        text = aliases[text]
    canon = _PY_TYPES.get(text)
    if canon is None:  # pragma: no cover - developer error
        raise SystemExit(f"check_native_table: unmapped ctypes expression {text!r}")
    return canon


def _module_aliases(module: ast.Module) -> dict[str, str]:
    """Simple ``NAME = expression`` assignments at module level."""
    aliases: dict[str, str] = {}
    for node in module.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            aliases[node.targets[0].id] = ast.unparse(node.value)
    return aliases


def _signatures_dict(module: ast.Module) -> ast.Dict:
    """The AST node of the annotated ``SIGNATURES = {...}`` assignment."""
    for node in module.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "SIGNATURES"
            and isinstance(node.value, ast.Dict)
        ):
            return node.value
    raise SystemExit("check_native_table: SIGNATURES dict not found in _native.py")


def _table_entry(
    key: ast.expr | None, value: ast.expr, aliases: dict[str, str]
) -> tuple[str, tuple[str, list[str]]]:
    """Canonicalize one ``"name": (restype, [argtypes])`` entry."""
    if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
        raise SystemExit("check_native_table: non-literal SIGNATURES key")
    if not (
        isinstance(value, ast.Tuple)
        and len(value.elts) == 2
        and isinstance(value.elts[1], ast.List)
    ):
        raise SystemExit(f"check_native_table: unexpected entry shape for {key.value}")
    restype, argtypes = value.elts[0], value.elts[1]
    args = [_canon_py(a, aliases) for a in argtypes.elts]
    return key.value, (_canon_py(restype, aliases), args)


def table_from_source() -> dict[str, tuple[str, list[str]]]:
    """Read SIGNATURES by parsing the module source — nothing is executed."""
    module = ast.parse(_native_source, filename="_native.py")
    aliases = _module_aliases(module)
    signatures = _signatures_dict(module)
    return dict(
        _table_entry(key, value, aliases)
        for key, value in zip(signatures.keys, signatures.values, strict=True)
    )


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    header_path = Path(sys.argv[1])
    if not header_path.is_file():
        print(f"header not found: {header_path}")
        return 2

    header = parse_header(header_path)
    table = table_from_source()

    problems: list[str] = []
    for name in sorted(set(header) - set(table)):
        problems.append(f"  missing from _native.SIGNATURES: {name}")
    for name in sorted(set(table) - set(header)):
        problems.append(f"  not present in helm_c.h: {name}")
    for name in sorted(set(header) & set(table)):
        if header[name] != table[name]:
            problems.append(
                f"  signature mismatch for {name}:\n"
                f"      header: {header[name]}\n"
                f"      table:  {table[name]}"
            )

    if problems:
        print("native declaration table does not match helm_c.h:")
        print("\n".join(problems))
        return 1

    print(f"native declaration table matches helm_c.h ({len(table)} symbols)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
