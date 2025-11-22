from __future__ import annotations

from types import SimpleNamespace

import pytest

from publisher_v2.core.exceptions import StorageError
from publisher_v2.services.storage import DropboxStorage


class _FakeApiError(Exception):
    def __init__(self, error=None) -> None:
        super().__init__("api error")
        self.error = error


class _FakeDropboxClient:
    def __init__(self) -> None:
        self.upload_calls: list[tuple[str, bytes]] = []
        self.download_map: dict[str, bytes] = {}
        self.download_errors: dict[str, Exception] = {}
        self.metadata_map: dict[str, object] = {}
        self.temp_links: dict[str, str] = {}
        self.list_entries: list[object] = []
        self.move_calls: list[tuple[str, str]] = []
        self.fail_moves: dict[str, Exception] = {}
        self.created_folders: list[str] = []

    def files_upload(self, data: bytes, path: str, mode, mute: bool) -> None:
        self.upload_calls.append((path, data))

    def files_download(self, path: str):
        if path in self.download_errors:
            raise self.download_errors[path]
        return None, SimpleNamespace(content=self.download_map.get(path, b""))

    def files_get_metadata(self, path: str):
        return self.metadata_map[path]

    def files_list_folder(self, path: str):
        return SimpleNamespace(entries=self.list_entries)

    def files_get_temporary_link(self, path: str):
        return SimpleNamespace(link=self.temp_links.get(path, f"https://{path}"))

    def files_move_v2(self, src: str, dst: str, autorename: bool = True) -> None:
        self.move_calls.append((src, dst))
        exc = self.fail_moves.get(src)
        if exc:
            raise exc

    def files_create_folder_v2(self, path: str) -> None:
        self.created_folders.append(path)


@pytest.fixture
def storage_fixture(monkeypatch: pytest.MonkeyPatch):
    class _StubMetadata:
        def __init__(self, name: str, content_hash: str = "", file_id: str | None = None, rev: str | None = None) -> None:
            self.name = name
            self.content_hash = content_hash
            self.id = file_id
            self.rev = rev

    monkeypatch.setattr("publisher_v2.services.storage.ApiError", _FakeApiError)
    monkeypatch.setattr("publisher_v2.services.storage.dropbox.files.FileMetadata", _StubMetadata)
    monkeypatch.setattr(
        "publisher_v2.services.storage.dropbox.files.WriteMode",
        SimpleNamespace(overwrite=object()),
    )

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("publisher_v2.services.storage.asyncio.to_thread", fake_to_thread)

    storage = DropboxStorage.__new__(DropboxStorage)
    client = _FakeDropboxClient()
    storage.client = client
    return storage, client, _StubMetadata


@pytest.mark.asyncio
async def test_sidecar_upload_and_download(storage_fixture) -> None:
    storage, client, _ = storage_fixture
    client.download_map["/Photos/image.txt"] = b"cached"

    await storage.write_sidecar_text("/Photos", "image.jpg", "hello")
    assert client.upload_calls[0][0] == "/Photos/image.txt"
    assert client.upload_calls[0][1] == b"hello"

    data = await storage.download_sidecar_if_exists("/Photos", "image.jpg")
    assert data == b"cached"


@pytest.mark.asyncio
async def test_download_sidecar_not_found(storage_fixture) -> None:
    storage, client, _ = storage_fixture

    class _PathError:
        def is_not_found(self) -> bool:
            return True

    class _ErrorObj:
        def is_path(self) -> bool:
            return True

        def get_path(self):
            return _PathError()

    client.download_errors["/Photos/image.txt"] = _FakeApiError(error=_ErrorObj())
    data = await storage.download_sidecar_if_exists("/Photos", "image.jpg")
    assert data is None


@pytest.mark.asyncio
async def test_download_sidecar_raises_storage_error(storage_fixture) -> None:
    storage, client, _ = storage_fixture
    client.download_errors["/Photos/image.txt"] = _FakeApiError(error=None)
    with pytest.raises(StorageError):
        await storage.download_sidecar_if_exists("/Photos", "image.jpg")


@pytest.mark.asyncio
async def test_metadata_and_listing_helpers(storage_fixture) -> None:
    storage, client, metadata_cls = storage_fixture
    client.metadata_map["/Photos/image.jpg"] = metadata_cls(name="image.jpg", file_id="id", rev="rev")
    meta = await storage.get_file_metadata("/Photos", "image.jpg")
    assert meta == {"id": "id", "rev": "rev"}

    client.list_entries = [
        metadata_cls(name="photo.JPG", content_hash="hash1"),
        metadata_cls(name="document.txt", content_hash="hash2"),
    ]
    names = await storage.list_images("/Photos")
    assert names == ["photo.JPG"]
    hashed = await storage.list_images_with_hashes("/Photos")
    assert hashed == [("photo.JPG", "hash1")]


@pytest.mark.asyncio
async def test_download_image_and_temp_link(storage_fixture) -> None:
    storage, client, _ = storage_fixture
    client.download_map["/Photos/image.jpg"] = b"img"
    client.temp_links["/Photos/image.jpg"] = "https://temp"

    data = await storage.download_image("/Photos", "image.jpg")
    assert data == b"img"
    link = await storage.get_temporary_link("/Photos", "image.jpg")
    assert link == "https://temp"


@pytest.mark.asyncio
async def test_move_and_archive_with_sidecar(storage_fixture) -> None:
    storage, client, _ = storage_fixture
    client.fail_moves["/Photos/image.txt"] = _FakeApiError()

    await storage.move_image_with_sidecars("/Photos", "image.jpg", "keep")
    assert client.created_folders == ["/Photos/keep"]
    assert ("/Photos/image.jpg", "/Photos/keep/image.jpg") in client.move_calls

    await storage.archive_image("/Photos", "image.jpg", "archive")
    assert ("/Photos/image.jpg", "/Photos/archive/image.jpg") in client.move_calls

