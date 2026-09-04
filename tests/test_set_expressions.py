"""The full ``--set`` expression family."""

from __future__ import annotations

from pathlib import Path

import pytest

import helm_python as helm


def test_parse_set_string_values_keeps_strings() -> None:
    assert helm.parse_set_string_values("port=80,name=web") == {"port": "80", "name": "web"}


def test_parse_set_json_values_are_documents() -> None:
    assert helm.parse_set_json('a={"b":[1,2]},c=null') == {"a": {"b": [1, 2]}, "c": None}


def test_parse_set_json_rejects_invalid_document() -> None:
    with pytest.raises(helm.HelmError):
        helm.parse_set_json("a={broken")


def test_parse_set_literal_is_verbatim() -> None:
    assert helm.parse_set_literal("a=b,c=d") == {"a": "b,c=d"}


def test_parse_set_file_reads_files(tmp_path: Path) -> None:
    payload = tmp_path / "value.txt"
    payload.write_text("from-file")
    # POSIX form: strvals treats backslashes as escapes, and Go accepts
    # forward-slash paths on Windows too.
    assert helm.parse_set_file(f"key={payload.as_posix()}") == {"key": "from-file"}


def test_parse_set_file_missing_file_raises(tmp_path: Path) -> None:
    expression = f"key={(tmp_path / 'absent.txt').as_posix()}"
    with pytest.raises(helm.HelmError):
        helm.parse_set_file(expression)
