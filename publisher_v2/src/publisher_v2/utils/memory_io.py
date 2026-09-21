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
        """Wrap ``data`` in a memoryview and start reading at offset 0.

        The buffer is exported, not copied, so it stays un-resizable until
        :meth:`close` releases it.
        """
        self._mv = memoryview(data)
        self._pos = 0

    def readable(self) -> bool:
        """Return True: the reader is always readable."""
        return True

    def seekable(self) -> bool:
        """Return True: the underlying buffer supports arbitrary seeks."""
        return True

    def tell(self) -> int:
        """Return the current read offset in bytes."""
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        """Move the read offset and return its new absolute value.

        Seeking past the end is allowed (reads then return no data), matching a real file.

        Raises:
            ValueError: ``whence`` is not one of SEEK_SET/SEEK_CUR/SEEK_END.
            OSError: The resulting offset would be negative.
        """
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
        """Copy up to ``len(buffer)`` bytes into ``buffer`` and return how many were copied.

        Returns 0 only at genuine end of buffer.

        Raises:
            ValueError: The reader has been closed — never reported as EOF, since a
                retried upload would then store an empty object with a valid checksum.
        """
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
