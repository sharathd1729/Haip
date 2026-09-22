"""SSRF protection for fetching URLs a user supplied.

Any feature that makes the server request a URL a tenant typed in (knowledge
base website import, a channel manager's base URL) must go through here.
Without it, a tenant owner -- and anyone can become one via /auth/register --
can point HAIP at the cloud metadata service, localhost, or another container
on the private network and read the response back.

Rules: http(s) only; every address the hostname resolves to must be public
(no private, loopback, link-local, multicast, reserved or unspecified
ranges); redirects are followed by hand so each hop is re-checked.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx


class UnsafeURLError(ValueError):
    """The URL points somewhere the server must not fetch."""


MAX_REDIRECTS = 5


def _ip_is_public(ip: ipaddress._BaseAddress) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified
    )


def assert_public_url(url: str, *, allow_http: bool = True) -> None:
    """Raise UnsafeURLError unless `url` is http(s) and every address its host
    resolves to is a public one."""
    parts = urlsplit(url)
    allowed = ("http", "https") if allow_http else ("https",)
    if parts.scheme not in allowed:
        raise UnsafeURLError(f"Only {' or '.join(allowed)} URLs are allowed.")
    host = parts.hostname
    if not host:
        raise UnsafeURLError("The URL has no host.")
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Couldn't resolve {host}.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%", 1)[0])
        if not _ip_is_public(ip):
            raise UnsafeURLError(f"{host} points to a private or internal address, which isn't allowed.")


def safe_get(url: str, *, timeout: float, headers: dict | None = None) -> httpx.Response:
    """GET a user-supplied URL, re-validating every redirect hop."""
    current = url
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            assert_public_url(current)
            resp = client.get(current, headers=headers)
            if 300 <= resp.status_code < 400 and resp.headers.get("location"):
                current = urljoin(current, resp.headers["location"])
                continue
            return resp
    raise UnsafeURLError("Too many redirects.")
