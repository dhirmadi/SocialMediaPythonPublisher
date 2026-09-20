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
        bases = {io.SEEK_SET: 0, io.SEEK_CUR: self._pos, io.SEEK_END: len(self._mv)}
        if whence not in bases:
            # What every other file object raises; a KeyError here would read as
            # a bug in the caller's dict handling rather than a bad argument.
            raise ValueError(f"invalid whence ({whence}, should be 0, 1 or 2)")
        target = bases[whence] + offset
        if target < 0:
            # A real file raises here. Clamping to 0 would let a malformed image
            # seek backwards past the start and silently re-read the header.
            raise OSError(22, "Invalid argument")
        self._pos = target
        return self._pos

    def close(self) -> None:
        """Release the exported buffer, then close.

        Without this the memoryview outlives the reader and keeps the caller's
        bytearray un-resizable until the garbage collector gets to it — a
        BufferError far from the code that caused it.
        """
        mv, self._mv = self._mv, memoryview(b"")
        mv.release()
        super().close()

    def readinto(self, buffer: Any) -> int:
        if self.closed:
            # Returning 0 here would read as a clean EOF: an upload retried
            # through a closed reader would store an empty object with a valid
            # checksum over the empty body, which no integrity check can catch.
            raise ValueError("read of closed file")
        n = max(0, min(len(buffer), len(self._mv) - self._pos))
        buffer[:n] = self._mv[self._pos : self._pos + n]
        self._pos += n
        return n


def reader_over(data: bytes | bytearray | memoryview) -> io.BufferedReader:
    """A buffered, seekable file object reading ``data`` in place."""
    return io.BufferedReader(MemoryReader(data))
