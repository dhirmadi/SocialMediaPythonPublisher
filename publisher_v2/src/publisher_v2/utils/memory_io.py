"""Zero-copy, read-only file objects over in-memory buffers (#136)."""

from __future__ import annotations

import io
from typing import Any


class MemoryReader(io.RawIOBase):
    """Read-only, seekable raw file over a buffer, without copying it.

    ``io.BytesIO(bytearray)`` copies its argument; this reads the caller's buffer
    in place, so a large upload is held in memory once.
    """

    def __init__(self, data: bytes | bytearray | memoryview) -> None:
        self._mv = memoryview(data)
        self._pos = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._pos, io.SEEK_END: len(self._mv)}[whence]
        self._pos = max(0, base + offset)
        return self._pos

    def readinto(self, buffer: Any) -> int:
        n = max(0, min(len(buffer), len(self._mv) - self._pos))
        buffer[:n] = self._mv[self._pos : self._pos + n]
        self._pos += n
        return n


def reader_over(data: bytes | bytearray | memoryview) -> io.BufferedReader:
    """A buffered, seekable file object reading ``data`` in place."""
    return io.BufferedReader(MemoryReader(data))
