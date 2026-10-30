"""The stochadex dependency contract, without touching the network."""

import hashlib
import json
import stat

import anyio
import httpx
import pytest

from robert import deps
from robert.mcp_server import http_app
from robert.project import MethodError


@pytest.fixture
def lock_copy(tmp_path, monkeypatch):
    path = tmp_path / "stochadex.json"
    path.write_text(deps.LOCK_PATH.read_text())
    monkeypatch.setattr(deps, "LOCK_PATH", path)
    return path


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBERT_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("STOCHADEX_BIN", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    deps.binary_version.cache_clear()
    return tmp_path / "home"


def fake_stochadex(path, version):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\necho 'stochadex {version} test/test'\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def test_lock_is_well_formed():
    lk = deps.lock()
    assert deps.supported(lk["version"])
    assert all(len(h) == 64 for h in lk["sha256"].values())
    assert deps.asset_name(system="Linux", machine="x86_64") in lk["sha256"]


def test_supported_range():
    assert deps.supported("v0.24.0") and deps.supported("0.24.9")
    assert not deps.supported("v0.23.0") and not deps.supported("v0.25.0")


@pytest.mark.parametrize("system,machine,accel,name", [
    ("Darwin", "arm64", False, "stochadex-darwin-arm64"),
    ("Linux", "aarch64", True, "stochadex-accel-linux-arm64"),
    ("Windows", "AMD64", False, "stochadex-windows-amd64.exe"),
])
def test_asset_names_match_release_assets(system, machine, accel, name):
    assert deps.asset_name(accel, system, machine) == name


def test_install_refuses_a_checksum_mismatch(fake_home, monkeypatch):
    monkeypatch.setattr(deps, "_download", lambda url: b"not the real binary")
    with pytest.raises(MethodError, match="checksum mismatch"):
        deps.install()
    assert not deps.managed_binary(deps.lock()["version"]).exists()


def test_install_writes_a_verified_binary(fake_home, monkeypatch, lock_copy):
    payload = f"#!/bin/sh\necho 'stochadex {deps.lock()['version']} test/test'\n".encode()
    lk = json.loads(lock_copy.read_text())
    lk["sha256"][deps.asset_name()] = hashlib.sha256(payload).hexdigest()
    lock_copy.write_text(json.dumps(lk))
    monkeypatch.setattr(deps, "_download", lambda url: payload)
    out = deps.install()
    assert out["status"] == "installed"
    assert deps.resolve().source == "managed"


def test_image_style_version_matches_the_lock(fake_home, monkeypatch, tmp_path):
    """The stochadex image stamps "0.24.0" where release binaries say "v0.24.0"."""
    unprefixed = deps.lock()["version"].lstrip("v")
    monkeypatch.setenv("STOCHADEX_BIN", str(fake_stochadex(tmp_path / "img/stochadex", unprefixed)))
    assert deps.resolve().version == deps.lock()["version"]


def test_resolve_rejects_unsupported_versions(fake_home, monkeypatch, tmp_path):
    old = fake_stochadex(tmp_path / "old/stochadex", "v0.19.0")
    monkeypatch.setenv("STOCHADEX_BIN", str(old))
    r = deps.resolve()
    assert r.binary is None and "v0.19.0" in r.problem and "robert setup" in r.problem


def test_resolve_prefers_the_wanted_managed_version(fake_home, monkeypatch, tmp_path):
    fake_stochadex(deps.managed_binary("v0.24.1"), "v0.24.1")
    monkeypatch.setenv("PATH", str(fake_stochadex(tmp_path / "p/stochadex", "v0.24.0").parent))
    r = deps.resolve("v0.24.1")
    assert (r.version, r.source) == ("v0.24.1", "managed")


def test_bump_reads_sha256sums_and_widens_the_range(monkeypatch, lock_copy):
    sums = "".join(f"{'a' * 64}  {n}\n" for n in
                   ["stochadex-linux-amd64", "stochadex-darwin-arm64"])
    monkeypatch.setattr(deps, "_download", lambda url: sums.encode())
    out = deps.bump("v0.25.2")
    lk = json.loads(lock_copy.read_text())
    assert out["changed"] and lk["version"] == "v0.25.2"
    assert lk["supported"] == [">=0.24.0", "<0.26.0"]
    assert set(lk["sha256"]) == {"stochadex-linux-amd64", "stochadex-darwin-arm64"}


def test_http_mcp_needs_a_token_off_loopback(monkeypatch):
    monkeypatch.delenv("ROBERT_MCP_TOKEN", raising=False)
    with pytest.raises(MethodError, match="ROBERT_MCP_TOKEN"):
        http_app("0.0.0.0")


def test_http_mcp_rejects_a_wrong_token():
    app = http_app("0.0.0.0", token="s3cret")

    async def main():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://pod") as c:
            bad = await c.post("/mcp", headers={"Authorization": "Bearer nope"}, json={})
            none = await c.post("/mcp", json={})
            return bad.status_code, none.status_code

    assert anyio.run(main) == (401, 401)
