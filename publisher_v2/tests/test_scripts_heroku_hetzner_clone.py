import importlib.util
import pathlib
from types import ModuleType
from typing import Any

import pytest


def _load_script_module() -> ModuleType:
    root = pathlib.Path(__file__).resolve().parents[2]
    script_path = root / "scripts" / "heroku_hetzner_clone.py"
    spec = importlib.util.spec_from_file_location(
        "heroku_hetzner_clone", script_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Ensure the module is registered so dataclasses and other decorators
    # that inspect sys.modules can resolve it correctly.
    import sys as _sys

    _sys.modules[spec.name] = module  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


class _DummyResponse:
    def __init__(self, status_code: int = 200, text: str = "", json_data: Any | None = None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data if json_data is not None else {}

    def json(self) -> Any:
        return self._json_data


class _BaseSession:
    def __init__(self, *, get=None, post=None, patch=None, delete=None, put=None):
        self._get = get
        self._post = post
        self._patch = patch
        self._delete = delete
        self._put = put
        self.headers: dict[str, str] = {}

    def get(self, url: str, timeout: int = 30, **_kwargs):
        assert self._get is not None
        return self._get(url, timeout)

    def post(self, url: str, json, timeout: int = 30, headers: dict[str, str] | None = None, **_kwargs):
        assert self._post is not None
        return self._post(url, json, timeout, headers)

    def patch(self, url: str, json, timeout: int = 30, **_kwargs):
        assert self._patch is not None
        return self._patch(url, json, timeout)

    def delete(self, url: str, timeout: int = 30, **_kwargs):
        assert self._delete is not None
        return self._delete(url, timeout)

    def put(self, url: str, json, timeout: int = 30, **_kwargs):
        assert self._put is not None
        return self._put(url, json, timeout)


def _prepare_scripts_dir(module: ModuleType, tmp_path: pathlib.Path, monkeypatch) -> pathlib.Path:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    fake_script = scripts_dir / "heroku_hetzner_clone.py"
    fake_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setattr(module, "__file__", str(fake_script))
    return scripts_dir


def _install_noop_clients(module: ModuleType, monkeypatch):
    class _Heroku:
        def delete_app(self, _app_name: str) -> None:
            return None

    class _Hetzner:
        def get_zone_by_name(self, _name: str):
            return {"id": "zone-id", "name": "zone"}

        def find_record(self, *, zone_id: str, name: str, rtype: str = "CNAME"):
            return None

        def delete_record(self, record_id: str) -> None:
            return None

    heroku = _Heroku()
    hetzner = _Hetzner()

    monkeypatch.setattr(
        module.HerokuClient,
        "from_env",
        classmethod(lambda cls: heroku),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        module.HetznerDNSClient,
        "from_env",
        classmethod(lambda cls: hetzner),  # type: ignore[arg-type]
    )
    return heroku, hetzner


def test_append_server_record_appends_line(tmp_path, monkeypatch) -> None:  # type: ignore[override]
    module = _load_script_module()
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    fake_script = scripts_dir / "heroku_hetzner_clone.py"
    fake_script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setattr(module, "__file__", str(fake_script))

    module.append_server_record(  # type: ignore[attr-defined]
        name="alice",
        folder="/Photos/alice",
        heroku_url="https://fetlife-prod-alice.herokuapp.com",
        subdomain_url="https://alice.shibari.photo",
    )

    servers_txt = scripts_dir / "servers.txt"
    contents = servers_txt.read_text(encoding="utf-8").strip()
    assert contents.startswith("alice,/Photos/alice,https://fetlife-prod-alice.herokuapp.com")
    assert contents.count(",") == 4


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://example.com",
        "https://foo.herokuapp.net",
    ],
)
def test_parse_app_name_from_url_invalid(url: str) -> None:
    module = _load_script_module()
    assert module._parse_app_name_from_heroku_url(url) is None  # type: ignore[attr-defined]


@pytest.mark.parametrize("label", ["", "bad!", "-start", "end-"])
def test_validate_subdomain_label_invalid(label: str) -> None:
    module = _load_script_module()
    with pytest.raises(ValueError):
        module.validate_subdomain_label(label)  # type: ignore[attr-defined]


def test_normalize_heroku_app_name_fallback_prefix(monkeypatch) -> None:
    module = _load_script_module()

    class _StubRE:
        def sub(self, pattern: str, repl: str, text: str) -> str:
            return ""

    monkeypatch.setattr(module, "re", _StubRE())  # type: ignore[attr-defined]
    assert module.normalize_heroku_app_name("???") == "a-instance"  # type: ignore[attr-defined]


def test_update_image_folder_rejects_empty_folder() -> None:
    module = _load_script_module()
    ini_text = "[Dropbox]\nimage_folder = foo\n"
    with pytest.raises(ValueError):
        module.update_image_folder(ini_text, "")  # type: ignore[attr-defined]


def test_heroku_client_from_env_requires_token(monkeypatch) -> None:
    module = _load_script_module()
    monkeypatch.delenv("HEROKU_API_TOKEN", raising=False)
    with pytest.raises(module.HerokuError):  # type: ignore[attr-defined]
        module.HerokuClient.from_env()  # type: ignore[attr-defined]


def test_hetzner_client_from_env_requires_token(monkeypatch) -> None:
    module = _load_script_module()
    monkeypatch.delenv("HETZNER_DNS_API_TOKEN", raising=False)
    with pytest.raises(module.HetznerDNSError):  # type: ignore[attr-defined]
        module.HetznerDNSClient.from_env()  # type: ignore[attr-defined]


def test_heroku_client_methods_raise_on_http_errors() -> None:
    module = _load_script_module()

    def _error_response(*_args, **_kwargs):
        return _DummyResponse(status_code=503, text="nope")

    session = _BaseSession(
        get=_error_response,
        post=_error_response,
        patch=_error_response,
        delete=_error_response,
        put=_error_response,
    )
    client = module.HerokuClient(api_token="token", session=session)  # type: ignore[attr-defined]

    with pytest.raises(module.HerokuError):
        client.get_app("foo")
    with pytest.raises(module.HerokuError):
        client.create_app("foo")
    with pytest.raises(module.HerokuError):
        client.add_app_to_pipeline("app-id", "pipeline-id")
    with pytest.raises(module.HerokuError):
        client.enable_acm("foo")
    with pytest.raises(module.HerokuError):
        client.get_config_vars("foo")
    with pytest.raises(module.HerokuError):
        client.set_config_vars("foo", {"A": "1"})
    with pytest.raises(module.HerokuError):
        client.create_domain("foo", "bar")
    with pytest.raises(module.HerokuError):
        client.delete_app("foo")


def test_heroku_client_get_pipeline_not_found() -> None:
    module = _load_script_module()

    def _pipelines_response(*_args, **_kwargs):
        return _DummyResponse(status_code=200, json_data=[{"name": "other", "id": "1"}])

    session = _BaseSession(get=_pipelines_response)
    client = module.HerokuClient(api_token="token", session=session)  # type: ignore[attr-defined]

    with pytest.raises(module.HerokuError):
        client.get_pipeline_by_name("missing")


def test_heroku_client_promote_release_error(monkeypatch) -> None:
    module = _load_script_module()

    def _post(_url: str, _json: Any, _timeout: int, _headers: dict[str, str] | None):
        return _DummyResponse(status_code=400, text="bad payload")

    session = _BaseSession(post=_post, get=lambda *_args: _DummyResponse(json_data={"id": "app-id"}))
    client = module.HerokuClient(api_token="token", session=session)  # type: ignore[attr-defined]

    # Stub get_app to avoid making HTTP requests for IDs
    monkeypatch.setattr(
        client,
        "get_app",
        lambda app_name: {"id": f"{app_name}-id"},
    )

    with pytest.raises(module.HerokuError):
        client.promote_release("source", "target", "pipeline-id")


def test_heroku_client_get_sni_endpoints_handles_errors() -> None:
    module = _load_script_module()
    session = _BaseSession(get=lambda *_args: _DummyResponse(status_code=404, text="none"))
    client = module.HerokuClient(api_token="token", session=session)  # type: ignore[attr-defined]
    assert client.get_sni_endpoints("foo") == []


def test_hetzner_client_methods_raise_on_http_errors() -> None:
    module = _load_script_module()

    def _error_response(*_args, **_kwargs):
        return _DummyResponse(status_code=422, text="nope")

    session = _BaseSession(
        get=_error_response,
        post=_error_response,
        put=_error_response,
        delete=_error_response,
    )
    client = module.HetznerDNSClient(api_token="token", session=session)  # type: ignore[attr-defined]

    with pytest.raises(module.HetznerDNSError):
        client.get_zone_by_name("foo")
    with pytest.raises(module.HetznerDNSError):
        client.find_record(zone_id="z", name="n")
    with pytest.raises(module.HetznerDNSError):
        client.create_record(zone_id="z", name="n", target="t")
    with pytest.raises(module.HetznerDNSError):
        client.update_record("id", name="n", target="t")
    with pytest.raises(module.HetznerDNSError):
        client.delete_record("id")


def test_hetzner_client_ensure_cname_update_branch(monkeypatch) -> None:
    module = _load_script_module()

    def _dummy_get(*_args, **_kwargs):
        return _DummyResponse(status_code=200, json_data={"records": []})

    session = _BaseSession(get=_dummy_get, post=_dummy_get, put=_dummy_get)
    client = module.HetznerDNSClient(api_token="token", session=session)  # type: ignore[attr-defined]

    called: dict[str, Any] = {}

    def _fake_find_record(**_kwargs):
        return {"id": "123"}

    def _fake_update(record_id: str, *, name: str, target: str, ttl: int = 300):
        called["record_id"] = record_id
        called["name"] = name
        called["target"] = target
        return {"id": record_id, "name": name, "value": target}

    monkeypatch.setattr(client, "find_record", _fake_find_record)
    monkeypatch.setattr(client, "update_record", _fake_update)

    result = client.ensure_cname(zone_id="zone", name="foo", target="bar", overwrite=True)
    assert result["id"] == "123"
    assert called["target"] == "bar"


def test_hetzner_client_ensure_cname_create_branch(monkeypatch) -> None:
    module = _load_script_module()

    session = _BaseSession(
        get=lambda *_args, **_kwargs: _DummyResponse(status_code=200, json_data={"records": []}),
        post=lambda *_args, **_kwargs: _DummyResponse(status_code=201, json_data={"id": "999"}),
    )
    client = module.HetznerDNSClient(api_token="token", session=session)  # type: ignore[attr-defined]

    monkeypatch.setattr(client, "find_record", lambda **_kwargs: None)

    created: dict[str, Any] = {}

    def _fake_create(**kwargs):
        created.update(kwargs)
        return {"id": "999", "name": kwargs["name"], "value": kwargs["target"]}

    monkeypatch.setattr(client, "create_record", _fake_create)

    result = client.ensure_cname(zone_id="zone", name="foo", target="bar", overwrite=True)
    assert result["id"] == "999"
    assert created["target"] == "bar"


def test_main_rejects_invalid_subdomain() -> None:
    module = _load_script_module()
    rc = module.main(["--name", "bad*name", "--dry-run"])  # type: ignore[attr-defined]
    assert rc == 1


def test_main_requires_folder_and_password_for_create() -> None:
    module = _load_script_module()
    rc = module.main(["--action", "create", "--name", "ok"])  # type: ignore[attr-defined]
    assert rc == 1


def test_main_handles_client_initialization_failure(monkeypatch) -> None:
    module = _load_script_module()

    def _raise_heroku():
        raise module.HerokuError("missing token")  # type: ignore[attr-defined]

    monkeypatch.setattr(
        module.HerokuClient,
        "from_env",
        classmethod(lambda cls: _raise_heroku()),
    )
    rc = module.main(["--action", "delete", "--name", "ok"])  # type: ignore[attr-defined]
    assert rc == 1


def test_main_create_missing_fetlife_ini(monkeypatch) -> None:  # type: ignore[override]
    module = _load_script_module()

    class _Heroku:
        def create_app(self, new_name: str):
            return {"id": "app-id", "name": new_name, "web_url": f"https://{new_name}.herokuapp.com"}

        def get_pipeline_by_name(self, _name: str):
            return {"id": "pipeline"}

        def add_app_to_pipeline(self, *_args, **_kwargs):
            return {"id": "coupling"}

        def get_config_vars(self, _app_name: str):
            return {"OTHER": "1"}

    class _Hetzner:
        pass

    monkeypatch.setattr(
        module.HerokuClient,
        "from_env",
        classmethod(lambda cls: _Heroku()),
    )
    monkeypatch.setattr(
        module.HetznerDNSClient,
        "from_env",
        classmethod(lambda cls: _Hetzner()),
    )

    rc = module.main(
        [
            "--action",
            "create",
            "--name",
            "ok",
            "--folder",
            "/Photos/ok",
            "--password",
            "pw",
            "--heroku-source-app",
            "fetlife-prod",
            "--dry-run",
        ]
    )  # type: ignore[attr-defined]
    assert rc == 0  # Dry runs skip validation beyond args

    # Now run without dry-run to trigger error
    rc2 = module.main(
        [
            "--action",
            "create",
            "--name",
            "ok",
            "--folder",
            "/Photos/ok",
            "--password",
            "pw",
            "--heroku-source-app",
            "fetlife-prod",
        ]
    )  # type: ignore[attr-defined]
    assert rc2 == 1


def test_main_create_missing_dns_target(monkeypatch) -> None:  # type: ignore[override]
    module = _load_script_module()

    class _Heroku:
        def create_app(self, new_name: str):
            return {"id": "app-id", "name": new_name, "web_url": f"https://{new_name}.herokuapp.com"}

        def get_pipeline_by_name(self, _name: str):
            return {"id": "pipeline"}

        def add_app_to_pipeline(self, *_args, **_kwargs):
            return {"id": "coupling"}

        def get_config_vars(self, _app_name: str):
            return {"FETLIFE_INI": "[Dropbox]\nimage_folder = /Photos/old\n"}

        def set_config_vars(self, *_args, **_kwargs):
            return None

        def enable_acm(self, _app_name: str):
            return {}

        def create_domain(self, _app_name: str, _hostname: str):
            return {}

    class _Hetzner:
        pass

    monkeypatch.setattr(
        module.HerokuClient,
        "from_env",
        classmethod(lambda cls: _Heroku()),
    )
    monkeypatch.setattr(
        module.HetznerDNSClient,
        "from_env",
        classmethod(lambda cls: _Hetzner()),
    )

    rc = module.main(
        [
            "--action",
            "create",
            "--name",
            "ok",
            "--folder",
            "/Photos/ok",
            "--password",
            "pw",
        ]
    )  # type: ignore[attr-defined]
    assert rc == 1


def test_main_logs_warning_when_servers_log_fails(monkeypatch) -> None:
    module = _load_script_module()

    class FakeHeroku:
        def __init__(self) -> None:
            self.created_apps = []

        def create_app(self, new_name: str):
            self.created_apps.append(new_name)
            return {"id": "new-app", "name": new_name, "web_url": f"https://{new_name}.herokuapp.com"}

        def get_pipeline_by_name(self, _name: str):
            return {"id": "pipeline"}

        def add_app_to_pipeline(self, *_args, **_kwargs):
            return {"id": "coupling"}

        def get_config_vars(self, _app_name: str):
            return {"FETLIFE_INI": "[Dropbox]\nimage_folder = /Photos/old\n"}

        def set_config_vars(self, *_args, **_kwargs):
            return None

        def enable_acm(self, _app_name: str):
            return {}

        def create_domain(self, _app_name: str, _hostname: str):
            return {"cname": "target.herokudns.com"}

        def promote_release(self, *_args, **_kwargs):
            return {"id": "promotion"}

    class FakeHetzner:
        def get_zone_by_name(self, _name: str):
            return {"id": "zone", "name": "shibari.photo"}

        def ensure_cname(self, **_kwargs):
            return {"id": "record"}

    monkeypatch.setattr(
        module.HerokuClient,
        "from_env",
        classmethod(lambda cls: FakeHeroku()),
    )
    monkeypatch.setattr(
        module.HetznerDNSClient,
        "from_env",
        classmethod(lambda cls: FakeHetzner()),
    )
    def _raise_append(*_args, **_kwargs):
        raise OSError("fs error")

    monkeypatch.setattr(
        module,
        "append_server_record",
        _raise_append,  # type: ignore[attr-defined]
    )

    rc = module.main(
        [
            "--action",
            "create",
            "--name",
            "warn",
            "--folder",
            "/Photos/warn",
            "--password",
            "pw",
        ]
    )  # type: ignore[attr-defined]
    assert rc == 0


def test_delete_requires_servers_file(monkeypatch, tmp_path) -> None:  # type: ignore[override]
    module = _load_script_module()
    _install_noop_clients(module, monkeypatch)
    _prepare_scripts_dir(module, tmp_path, monkeypatch)
    rc = module.main(["--action", "delete", "--name", "ghost"])  # type: ignore[attr-defined]
    assert rc == 1


def test_delete_empty_servers_file(monkeypatch, tmp_path) -> None:  # type: ignore[override]
    module = _load_script_module()
    _install_noop_clients(module, monkeypatch)
    scripts_dir = _prepare_scripts_dir(module, tmp_path, monkeypatch)
    (scripts_dir / "servers.txt").write_text("", encoding="utf-8")

    rc = module.main(["--action", "delete", "--name", "ghost"])  # type: ignore[attr-defined]
    assert rc == 1


def test_delete_no_matching_record(monkeypatch, tmp_path) -> None:  # type: ignore[override]
    module = _load_script_module()
    _install_noop_clients(module, monkeypatch)
    scripts_dir = _prepare_scripts_dir(module, tmp_path, monkeypatch)
    (scripts_dir / "servers.txt").write_text(
        "other,/Photos,https://app.herokuapp.com,https://other.shibari.photo,2024-01-01T00:00:00Z\n",
        encoding="utf-8",
    )

    rc = module.main(["--action", "delete", "--name", "ghost"])  # type: ignore[attr-defined]
    assert rc == 1


def test_delete_handles_malformed_lines(monkeypatch, tmp_path) -> None:  # type: ignore[override]
    module = _load_script_module()
    _install_noop_clients(module, monkeypatch)
    scripts_dir = _prepare_scripts_dir(module, tmp_path, monkeypatch)
    servers_txt = scripts_dir / "servers.txt"
    servers_txt.write_text(
        "bad-line\n"
        "ghost,/Photos,https://fetlife-prod-ghost.herokuapp.com,https://ghost.shibari.photo,2024-01-01T00:00:00Z\n",
        encoding="utf-8",
    )

    class _WarnHeroku:
        def delete_app(self, _app_name: str) -> None:
            return None

    class _WarnHetzner:
        def get_zone_by_name(self, _name: str):
            return {"id": "zone", "name": "zone"}

        def find_record(self, *, zone_id: str, name: str, rtype: str = "CNAME"):
            return {"id": "record-id", "name": name, "type": rtype}

        def delete_record(self, record_id: str) -> None:
            return None

    monkeypatch.setattr(
        module.HerokuClient,
        "from_env",
        classmethod(lambda cls: _WarnHeroku()),
    )
    monkeypatch.setattr(
        module.HetznerDNSClient,
        "from_env",
        classmethod(lambda cls: _WarnHetzner()),
    )

    rc = module.main(["--action", "delete", "--name", "ghost"])  # type: ignore[attr-defined]
    assert rc == 0
    remaining = servers_txt.read_text(encoding="utf-8")
    assert remaining == "bad-line\n"


def test_delete_warns_when_heroku_or_dns_fail(monkeypatch, tmp_path) -> None:  # type: ignore[override]
    module = _load_script_module()
    scripts_dir = _prepare_scripts_dir(module, tmp_path, monkeypatch)
    servers_txt = scripts_dir / "servers.txt"
    servers_txt.write_text(
        "ghost,/Photos,https://fetlife-prod-ghost.herokuapp.com,https://ghost.shibari.photo,2024-01-01T00:00:00Z\n",
        encoding="utf-8",
    )

    class _WarnHeroku:
        def delete_app(self, _app_name: str) -> None:
            raise module.HerokuError("boom")  # type: ignore[attr-defined]

    class _WarnHetzner:
        def get_zone_by_name(self, _name: str):
            return {"id": "zone", "name": "zone"}

        def find_record(self, *, zone_id: str, name: str, rtype: str = "CNAME"):
            return {"id": "record-id", "name": name, "type": rtype}

        def delete_record(self, record_id: str) -> None:
            raise module.HetznerDNSError("boom")  # type: ignore[attr-defined]

    monkeypatch.setattr(
        module.HerokuClient,
        "from_env",
        classmethod(lambda cls: _WarnHeroku()),
    )
    monkeypatch.setattr(
        module.HetznerDNSClient,
        "from_env",
        classmethod(lambda cls: _WarnHetzner()),
    )

    rc = module.main(["--action", "delete", "--name", "ghost"])  # type: ignore[attr-defined]
    assert rc == 0
    assert servers_txt.read_text(encoding="utf-8") == ""


def test_update_image_folder_updates_dropbox_section() -> None:
    module = _load_script_module()
    ini_text = """
[Dropbox]
image_folder = /Photos/old
archive = archive

[Other]
foo = bar
"""
    updated = module.update_image_folder(ini_text, "/Photos/new")  # type: ignore[attr-defined]

    assert "[Dropbox]" in updated
    assert "image_folder = /Photos/new" in updated
    assert "[Other]" in updated
    assert "foo = bar" in updated


def test_update_image_folder_raises_for_missing_section_or_key() -> None:
    module = _load_script_module()

    ini_missing_section = """
[Other]
foo = bar
"""
    ini_missing_key = """
[Dropbox]
archive = archive
"""

    for bad in (ini_missing_section, ini_missing_key):
        try:
            module.update_image_folder(bad, "/Photos/new")  # type: ignore[attr-defined]
        except ValueError:
            # Expected
            continue
        raise AssertionError("Expected ValueError for invalid FETLIFE_INI")


def test_normalize_heroku_app_name_and_parse_url_roundtrip() -> None:
    module = _load_script_module()

    # Name with uppercase and invalid chars should be normalized
    app_name = module.normalize_heroku_app_name("Tati_01")  # type: ignore[attr-defined]
    assert app_name.startswith("fetlife-prod-")
    assert app_name == app_name.lower()
    assert "." not in app_name
    assert "_" not in app_name

    # Construct a Heroku URL and ensure we can parse the app name back
    heroku_url = f"https://{app_name}.herokuapp.com"
    parsed = module._parse_app_name_from_heroku_url(heroku_url)  # type: ignore[attr-defined]
    assert parsed == app_name


def test_main_create_dry_run_requires_only_name() -> None:
    module = _load_script_module()
    # Should not raise even without --folder/--password because dry-run short-circuits
    rc = module.main(["--action", "create", "--name", "dryrun", "--dry-run"])  # type: ignore[attr-defined]
    assert rc == 0


def test_main_create_happy_path_uses_clients(monkeypatch) -> None:  # type: ignore[override]
    module = _load_script_module()

    class FakeHerokuClient:
        def __init__(self) -> None:
            self.created_apps = []
            self.pipelines = {}
            self.couplings = []
            self.config_get = {}
            self.config_set = {}
            self.acm_enabled = []
            self.domains = []
            self.promotions = []

        # from_env will return this instance directly
        def create_app(self, new_name: str):
            self.created_apps.append(new_name)
            return {"id": "new-app-id", "name": new_name, "web_url": f"https://{new_name}.herokuapp.com"}

        def get_pipeline_by_name(self, pipeline_name: str):
            self.pipelines[pipeline_name] = {"id": "pipeline-id", "name": pipeline_name}
            return self.pipelines[pipeline_name]

        def add_app_to_pipeline(self, app_id: str, pipeline_id: str, stage: str = "production"):
            self.couplings.append((app_id, pipeline_id, stage))
            return {"id": "coupling-id"}

        def get_config_vars(self, app_name: str):
            # Minimal config with FETLIFE_INI and one flag to test overwriting
            self.config_get[app_name] = True
            return {
                "FETLIFE_INI": "[Dropbox]\nimage_folder = /Photos/old\n",
                "FEATURE_PUBLISH": "true",
            }

        def set_config_vars(self, app_name: str, config):
            self.config_set[app_name] = config

        def enable_acm(self, app_name: str):
            self.acm_enabled.append(app_name)
            return {}

        def create_domain(self, app_name: str, hostname: str):
            self.domains.append((app_name, hostname))
            return {"cname": "opaque.herokudns.com"}

        def get_app(self, app_name: str):
            # Return fake ids for staging and new app
            if app_name == "fetlife":
                return {"id": "staging-app-id", "name": app_name}
            return {"id": "new-app-id", "name": app_name}

        def promote_release(self, source_app: str, target_app: str, pipeline_id: str):
            self.promotions.append((source_app, target_app, pipeline_id))
            return {"id": "promotion-id"}

    class FakeHetznerClient:
        def __init__(self) -> None:
            self.zones = {}
            self.cnames = []

        def get_zone_by_name(self, name: str):
            self.zones[name] = {"id": "zone-id", "name": name}
            return self.zones[name]

        def ensure_cname(self, *, zone_id: str, name: str, target: str, overwrite: bool = True):
            self.cnames.append((zone_id, name, target, overwrite))
            return {"id": "record-id", "name": name, "value": target}

    fake_heroku = FakeHerokuClient()
    fake_hetzner = FakeHetznerClient()

    # Patch clients and server logging to avoid touching the real servers.txt
    monkeypatch.setattr(
        module.HerokuClient,
        "from_env",
        classmethod(lambda cls: fake_heroku),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        module.HetznerDNSClient,
        "from_env",
        classmethod(lambda cls: fake_hetzner),  # type: ignore[arg-type]
    )
    records = []

    def _fake_append(name: str, folder: str, heroku_url: str, subdomain_url: str) -> None:
        records.append((name, folder, heroku_url, subdomain_url))

    monkeypatch.setattr(module, "append_server_record", _fake_append)  # type: ignore[attr-defined]

    rc = module.main(  # type: ignore[attr-defined]
        [
            "--action",
            "create",
            "--name",
            "tati",
            "--folder",
            "/Photos/tati",
            "--password",
            "pw",
            "--heroku-source-app",
            "fetlife-prod",
            "--heroku-staging-app",
            "fetlife",
            "--pipeline",
            "fetlife",
            "--pipeline-stage",
            "production",
        ]
    )

    assert rc == 0
    # Heroku app was created with the normalized name
    assert fake_heroku.created_apps == ["fetlife-prod-tati"]
    # Config vars were set on the new app and include our enforced flags
    new_cfg = fake_heroku.config_set["fetlife-prod-tati"]
    assert new_cfg["FETLIFE_INI"].strip().startswith("[Dropbox]")
    assert new_cfg["FEATURE_KEEP_CURATE"] == "true"
    assert new_cfg["FEATURE_REMOVE_CURATE"] == "true"
    assert new_cfg["FEATURE_ANALYZE_CAPTION"] == "false"
    assert new_cfg["FEATURE_PUBLISH"] == "false"
    assert new_cfg["AUTO_VIEW"] == "false"
    assert new_cfg["web_admin_pw"] == "pw"
    # CNAME was ensured and a server record logged
    assert fake_hetzner.cnames
    assert records and records[0][0] == "tati"


def test_main_delete_dry_run_and_real(monkeypatch, tmp_path) -> None:  # type: ignore[override]
    module = _load_script_module()

    # Arrange a temporary servers.txt and patch Path to point to tmp for this test
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    servers_path = scripts_dir / "servers.txt"
    servers_path.write_text(
        "tati,/Photos/tati,https://fetlife-prod-tati.herokuapp.com,https://tati.shibari.photo,2025-11-21T18:42:10Z\n",
        encoding="utf-8",
    )

    # Patch Path used in the script to resolve to our tmp scripts dir
    original_path_cls = module.Path  # type: ignore[attr-defined]

    class _TmpPathFactory(type(original_path_cls)):  # type: ignore[type-arg]
        def __new__(cls, *args, **kwargs):
            # Ignore the provided __file__ and always construct paths under tmp scripts dir
            return original_path_cls(scripts_dir / args[0])  # type: ignore[call-arg]

    monkeypatch.setattr(module, "Path", original_path_cls)

    # Instead of trying to replace Path globally (which is brittle), monkeypatch
    # the specific usage inside delete helper by pointing __file__ into tmp.
    fake_file = str(scripts_dir / "heroku_hetzner_clone.py")
    monkeypatch.setattr(module, "__file__", fake_file)

    # Fake clients to avoid real API calls
    class FakeHerokuClient:
        def __init__(self) -> None:
            self.deleted_apps = []

        def delete_app(self, app_name: str) -> None:
            self.deleted_apps.append(app_name)

    class FakeHetznerClient:
        def __init__(self) -> None:
            self.zones = {}
            self.deleted_records = []

        def get_zone_by_name(self, name: str):
            self.zones[name] = {"id": "zone-id", "name": name}
            return self.zones[name]

        def find_record(self, *, zone_id: str, name: str, rtype: str = "CNAME"):
            return {"id": "record-id", "name": name, "type": rtype}

        def delete_record(self, record_id: str) -> None:
            self.deleted_records.append(record_id)

    fake_heroku = FakeHerokuClient()
    fake_hetzner = FakeHetznerClient()

    monkeypatch.setattr(
        module.HerokuClient,
        "from_env",
        classmethod(lambda cls: fake_heroku),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(
        module.HetznerDNSClient,
        "from_env",
        classmethod(lambda cls: fake_hetzner),  # type: ignore[arg-type]
    )

    # Dry-run delete should not touch servers.txt or clients
    rc = module.main(  # type: ignore[attr-defined]
        ["--action", "delete", "--name", "tati", "--dry-run"]
    )
    assert rc == 0
    assert "tati" in servers_path.read_text(encoding="utf-8")
    assert not fake_heroku.deleted_apps
    assert not fake_hetzner.deleted_records

    # Real delete should delete the app, DNS record, and remove the line
    rc2 = module.main(  # type: ignore[attr-defined]
        ["--action", "delete", "--name", "tati"]
    )
    assert rc2 == 0
    assert "tati" not in servers_path.read_text(encoding="utf-8")
    assert fake_heroku.deleted_apps == ["fetlife-prod-tati"]
    assert fake_hetzner.deleted_records == ["record-id"]


