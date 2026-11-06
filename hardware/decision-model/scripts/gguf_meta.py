#!/usr/bin/env python3
"""Minimal GGUF metadata reader.

Only the key/value section is parsed, so reading a multi-gigabyte model file
costs a few hundred kilobytes of I/O. Scalars and string arrays are returned;
tensor data is never touched.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

_SCALARS = {
    0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i",
    6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d",
}
_NAMES = {
    0: "u8", 1: "i8", 2: "u16", 3: "i16", 4: "u32", 5: "i32",
    6: "f32", 7: "bool", 8: "str", 9: "array", 10: "u64", 11: "i64", 12: "f64",
}


def read_metadata(path: str | Path, max_bytes: int = 128 * 1024 * 1024) -> dict[str, Any]:
    """Return the GGUF key/value metadata of a model file."""
    path = Path(path)
    with path.open("rb") as handle:
        header = handle.read(24)
        if len(header) < 24 or header[:4] != b"GGUF":
            raise ValueError(f"{path} is not a GGUF file")
        version = struct.unpack_from("<I", header, 4)[0]
        tensor_count = struct.unpack_from("<Q", header, 8)[0]
        kv_count = struct.unpack_from("<Q", header, 16)[0]
        buffer = handle.read(64 * 1024 * 1024)

    offset = 0

    def u32() -> int:
        nonlocal offset
        value = struct.unpack_from("<I", buffer, offset)[0]
        offset += 4
        return value

    def u64() -> int:
        nonlocal offset
        value = struct.unpack_from("<Q", buffer, offset)[0]
        offset += 8
        return value

    def string() -> str:
        nonlocal offset
        length = u64()
        value = buffer[offset : offset + length].decode("utf-8", "replace")
        offset += length
        return value

    def value(kind: int) -> Any:
        nonlocal offset
        if kind == 8:
            return string()
        if kind == 9:
            element = u32()
            count = u64()
            if element == 8:
                items = []
                for _ in range(count):
                    items.append(string())
                return items
            fmt = _SCALARS[element]
            size = struct.calcsize(fmt)
            head = list(struct.unpack_from(f"<{min(count, 4)}{fmt[1]}", buffer, offset))[:4]
            offset += size * count
            return head
        fmt = _SCALARS[kind]
        result = struct.unpack_from(fmt, buffer, offset)[0]
        offset += struct.calcsize(fmt)
        return result

    # version, tensor count and kv count were read from the header
    metadata: dict[str, Any] = {}
    for _ in range(kv_count):
        if offset + 8 > len(buffer):
            break
        key = string()
        metadata[key] = value(u32())
    return metadata


def decision_type(path: str | Path) -> str | None:
    """Return the native decision type of a GGUF model, e.g. 'pplx-decider' or 'vllm-d3'."""
    metadata = read_metadata(path)
    architecture = metadata.get("general.architecture")
    if not isinstance(architecture, str):
        return None
    value = metadata.get(f"{architecture}.decision.type")
    return value if isinstance(value, str) else None


if __name__ == "__main__":
    import sys

    for target in sys.argv[1:]:
        print(target, "->", decision_type(target))
