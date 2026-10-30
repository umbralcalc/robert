"""The stochadex dependency: which versions robert supports, and installing them.

`stochadex.json` is the lock: the default version, the supported range, and the
SHA-256 of every release asset of the default version. robert installs stochadex
itself into `~/.robert/stochadex/<version>/` and refuses any binary it cannot verify
or whose version falls outside the range. Resolution order for the binary:
STOCHADEX_BIN, then the managed install of the wanted version, then PATH.

`python -m robert.deps bump` moves the lock to the newest stochadex release; the
weekly update workflow runs it and opens a PR.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .project import MethodError

LOCK_PATH = Path(__file__).with_name("stochadex.json")


def lock() -> dict[str, Any]:
    return json.loads(LOCK_PATH.read_text())


def parse(version: str) -> tuple[int, int, int]:
    core = version.strip().lstrip("v").split("-")[0]
    major, minor, patch = (int(x) for x in core.split("."))
    return major, minor, patch


def supported(version: str) -> bool:
    v = parse(version)
    for bound in lock()["supported"]:
        m = re.fullmatch(r"(>=|<=|>|<)\s*v?([\d.]+)", bound.strip())
        if not m:
            raise MethodError(f"stochadex.json: bad version bound {bound!r}")
        op, ref = m.group(1), parse(m.group(2))
        if not {">=": v >= ref, ">": v > ref, "<=": v <= ref, "<": v < ref}[op]:
            return False
    return True


def range_text() -> str:
    return ",".join(lock()["supported"])


def home() -> Path:
    return Path(os.environ.get("ROBERT_HOME", Path.home() / ".robert"))


def asset_name(accelerated: bool = False, system: str | None = None,
               machine: str | None = None) -> str:
    os_name = (system or platform.system()).lower()
    arch = (machine or platform.machine()).lower()
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(arch, arch)
    if os_name not in ("darwin", "linux", "windows") or arch not in ("amd64", "arm64"):
        raise MethodError(f"no stochadex release for {os_name}/{arch}")
    name = f"stochadex-{'accel-' if accelerated else ''}{os_name}-{arch}"
    return name + (".exe" if os_name == "windows" else "")


def managed_dir(version: str) -> Path:
    return home() / "stochadex" / version


def managed_binary(version: str) -> Path:
    return managed_dir(version) / ("stochadex.exe" if sys.platform == "win32" else "stochadex")


@functools.lru_cache(maxsize=None)
def binary_version(path: str) -> str | None:
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True,
                             timeout=30).stdout.split()
    except (OSError, subprocess.TimeoutExpired):
        return None
    if len(out) < 2 or out[0] != "stochadex":
        return None
    # Release binaries say "v0.23.0" and the OCI image says "0.23.0"; keep one form.
    return out[1] if out[1].startswith("v") or not out[1][:1].isdigit() else "v" + out[1]


@dataclass
class Resolved:
    binary: str | None
    version: str | None
    source: str
    problem: str | None = None


def resolve(wanted: str | None = None) -> Resolved:
    """Find a stochadex binary for `wanted` (default: the lock's version)."""
    wanted = wanted or lock()["version"]
    candidates = []
    if os.environ.get("STOCHADEX_BIN"):
        candidates.append(("STOCHADEX_BIN", os.environ["STOCHADEX_BIN"]))
    candidates.append(("managed", str(managed_binary(wanted))))
    if shutil.which("stochadex"):
        candidates.append(("PATH", shutil.which("stochadex")))

    problems = []
    for source, path in candidates:
        if not Path(path).exists():
            continue
        found = binary_version(path)
        if found is None:
            problems.append(f"{path} ({source}) does not report a stochadex version")
        elif not supported(found):
            problems.append(f"{path} ({source}) is {found}; robert supports {range_text()}")
        else:
            return Resolved(path, found, source)
    problem = "; ".join(problems) or "stochadex is not installed"
    return Resolved(None, None, "none",
                    problem + ". Run `robert setup` to install the pinned version.")


# --- installing -------------------------------------------------------------------


def _download(url: str) -> bytes:
    # httpx (via the mcp dependency) verifies against certifi's CA bundle, which
    # works on Python installs that ship without system certificates.
    try:
        r = httpx.get(url, follow_redirects=True, timeout=300,
                      headers={"User-Agent": "robert-installer"})
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise DownloadError(f"could not download {url}: {e}") from e
    return r.content


class DownloadError(MethodError):
    pass


def _release_url(version: str, name: str) -> str:
    return f"https://github.com/{lock()['repository']}/releases/download/{version}/{name}"


def expected_sha256(version: str, name: str) -> str:
    """The checksum to verify against: the lock's for the locked version, otherwise
    the release's own SHA256SUMS."""
    lk = lock()
    if version == lk["version"]:
        if name not in lk["sha256"]:
            raise MethodError(f"the lock has no checksum for {name}")
        return lk["sha256"][name]
    try:
        sums = _download(_release_url(version, "SHA256SUMS")).decode()
    except DownloadError as e:
        raise MethodError(f"{version} publishes no SHA256SUMS, so it cannot be verified; "
                          "install the locked version instead") from e
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            return parts[0]
    raise MethodError(f"SHA256SUMS for {version} does not list {name}")


def install(version: str | None = None, accelerated: bool = False,
            force: bool = False) -> dict[str, Any]:
    version = version or lock()["version"]
    if not version.startswith("v"):
        version = "v" + version
    if not supported(version):
        raise MethodError(f"stochadex {version} is outside robert's supported range "
                          f"{range_text()}")
    target = managed_binary(version)
    result: dict[str, Any] = {"version": version, "path": str(target)}
    if target.exists() and not force and binary_version(str(target)) == version:
        result["status"] = "already installed"
    else:
        name = asset_name(accelerated)
        want = expected_sha256(version, name)
        data = _download(_release_url(version, name))
        got = hashlib.sha256(data).hexdigest()
        if got != want:
            raise MethodError(f"checksum mismatch for {name}: expected {want}, got {got}; "
                              "nothing was installed")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as tmp:
            tmp.write(data)
        os.chmod(tmp.name, 0o755)
        os.replace(tmp.name, target)
        binary_version.cache_clear()
        result.update(status="installed", asset=name, sha256=got)
    return result


# --- moving the lock ---------------------------------------------------------------


def latest_release() -> str:
    data = json.loads(_download(f"https://api.github.com/repos/{lock()['repository']}"
                                "/releases/latest"))
    return data["tag_name"]


def bump(version: str | None = None) -> dict[str, Any]:
    """Move the lock to `version` (default: the latest release), verified by its
    SHA256SUMS, and widen the supported range to cover it."""
    lk = lock()
    version = version or latest_release()
    if version == lk["version"]:
        return {"changed": False, "version": version}
    sums = _download(_release_url(version, "SHA256SUMS")).decode()
    sha = {}
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith("stochadex"):
            sha[parts[1].lstrip("*")] = parts[0]
    if not sha:
        raise MethodError(f"{version} has an empty SHA256SUMS")
    major, minor, _ = parse(version)
    lk.update(version=version, sha256=dict(sorted(sha.items())))
    if not supported(version):
        # Keep the lower bound, so projects pinned to older releases still resolve;
        # the update PR's tests are what vouch for the new upper bound.
        lower = [b for b in lk["supported"] if b.startswith(">")]
        lk["supported"] = lower + [f"<{major}.{minor + 1}.0"]
    LOCK_PATH.write_text(json.dumps(lk, indent=2) + "\n")
    return {"changed": True, "version": version, "supported": lk["supported"]}


if __name__ == "__main__":  # pragma: no cover
    if sys.argv[1:2] == ["bump"]:
        print(json.dumps(bump(sys.argv[2] if len(sys.argv) > 2 else None)))
    else:
        print("usage: python -m robert.deps bump [vX.Y.Z]", file=sys.stderr)
        sys.exit(64)
