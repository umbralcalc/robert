"""Which hosts a sandbox may reach.

The sandbox network has no route out except an allowlisting proxy. It allows the
Anthropic API (the worker posts the session's tool results there) and the hosts
the project's `data/licences.yaml` names - so the record of why a data source is
used is also what opens the network to it. Everything else is refused.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import yaml

BASE_HOSTS = ["api.anthropic.com"]
PROXY_PORT = 3128


def project_hosts(project_dir: Path) -> list[str]:
    """Hosts from data/licences.yaml: an entry's `hosts:` list, else its `source` URL's host."""
    path = Path(project_dir) / "data/licences.yaml"
    if not path.exists():
        return []
    entries = yaml.safe_load(path.read_text()) or {}
    hosts: set[str] = set()
    for entry in entries.values():
        if not isinstance(entry, dict):
            continue
        listed = entry.get("hosts")
        if listed:
            hosts.update(str(h).strip().lower() for h in listed)
            continue
        source = str(entry.get("source", ""))
        if source.startswith(("http://", "https://")):
            if host := urlparse(source).hostname:
                hosts.add(host.lower())
    return sorted(hosts)


def allowlist(project_dirs: list[Path]) -> list[str]:
    hosts = set(BASE_HOSTS)
    for d in project_dirs:
        hosts.update(project_hosts(d))
    return sorted(hosts)


def squid_conf() -> str:
    """Allow CONNECT and plain HTTP only to hosts in /etc/squid/allowlist.txt."""
    return f"""\
http_port {PROXY_PORT}
acl allowed dstdomain "/etc/squid/allowlist.txt"
acl SSL_ports port 443
acl CONNECT method CONNECT
http_access deny CONNECT !SSL_ports
http_access allow allowed
http_access deny all
cache deny all
# squid drops to its own user, which cannot open /dev/stdout; read these with
# `docker exec robert-egress tail /var/log/squid/access.log`.
access_log stdio:/var/log/squid/access.log
cache_log /var/log/squid/cache.log
pid_filename none
"""


def allowlist_text(hosts: list[str]) -> str:
    return "".join(f"{h}\n" for h in hosts)


PROXY_DOCKERFILE = """\
FROM alpine:3.20
RUN apk add --no-cache squid
ENTRYPOINT ["squid", "-N", "-f", "/etc/squid/robert.conf"]
"""
