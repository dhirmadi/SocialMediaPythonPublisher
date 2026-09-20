"""#136: the zero-copy reader the upload path hands to Pillow and botocore."""

from __future__ import annotations

import io

import pytest

from publisher_v2.utils.memory_io import MemoryReader, reader_over


class TestSeek:
    def test_each_whence_is_honoured(self) -> None:
        reader = MemoryReader(bytearray(b"0123456789"))

        assert reader.seek(3) == 3
        assert reader.seek(2, io.SEEK_CUR) == 5
        assert reader.seek(-2, io.SEEK_END) == 8

    def test_seeking_before_the_start_raises(self) -> None:
        """A real file raises; clamping would let a malformed image silently re-read the header."""
        reader = MemoryReader(b"0123456789")

        with pytest.raises(OSError, match="Invalid argument"):
            reader.seek(-99)

        with pytest.raises(OSError):
            reader.seek(-1, io.SEEK_CUR)

    def test_an_invalid_whence_raises_value_error(self) -> None:
        """What every other file object raises; a KeyError would read as an internal bug."""
        reader = MemoryReader(b"0123456789")

        with pytest.raises(ValueError, match="whence"):
            reader.seek(0, 99)


class TestZeroCopy:
    def test_the_reader_sees_the_caller_s_buffer(self) -> None:
        """A copy (io.BytesIO's behaviour) would hold a second copy of the upload."""
        buf = bytearray(b"original")
        reader = reader_over(buf)
        buf[0:1] = b"O"

        assert reader.read() == b"Original"

    def test_reading_returns_every_byte_across_buffered_chunks(self) -> None:
        payload = bytes(range(256)) * 400
        assert reader_over(bytearray(payload)).read() == payload


class TestTheBufferStaysPinnedWhileRead:
    """The upload route must not append to the buffer once a reader exists.

    ``_verify_image_bytes`` and ``put_object`` both take a ``memoryview`` over
    the upload's bytearray. A bytearray cannot be resized while an exported
    buffer is live, so a later ``extend()`` raises at runtime — the comment in
    ``library.py`` says so, and this is that claim as a test.
    """

    def test_extending_the_buffer_under_a_live_reader_raises(self) -> None:
        buf = bytearray(b"pinned")
        reader = reader_over(buf)

        with pytest.raises(BufferError):
            buf.extend(b"more")

        assert reader.read() == b"pinned"

    def test_reading_after_close_raises_instead_of_reporting_eof(self) -> None:
        """A silent EOF would store an empty object with a checksum over the empty body."""
        raw = MemoryReader(bytearray(b"pinned"))
        raw.close()

        with pytest.raises(ValueError, match="closed"):
            raw.readinto(bytearray(4))

    def test_the_buffer_is_resizable_again_once_the_reader_is_gone(self) -> None:
        buf = bytearray(b"pinned")
        reader = reader_over(buf)
        reader.close()

        buf.extend(b"more")

        assert bytes(buf) == b"pinnedmore"
