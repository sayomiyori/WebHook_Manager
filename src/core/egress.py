from __future__ import annotations

import ipaddress
import socket

import httpx


class UnsafeDestination(ValueError):
    pass


def _address_allowed(address: str, trusted: bool) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _address_allowed(str(ip.ipv4_mapped), trusted)
    if isinstance(ip, ipaddress.IPv6Address) and (
        ip.sixtofour is not None
        or ip.teredo is not None
        or ip in ipaddress.IPv6Network("64:ff9b::/96")
        or ip in ipaddress.IPv6Network("64:ff9b:1::/48")
    ):
        return False
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return False
    return ip.is_global or (trusted and (ip.is_private or ip.is_loopback))


def validate_destination(url: str, trusted_origins: list[str]) -> httpx.URL:
    try:
        parsed = httpx.URL(url)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.host
            or parsed.userinfo
            or parsed.fragment
            or any(ord(char) < 33 for char in url)
        ):
            raise UnsafeDestination("Unsafe destination")
        origin = str(parsed.copy_with(path="/", query=None, fragment=None)).rstrip("/")
        trusted = origin in trusted_origins
        try:
            ip = ipaddress.ip_address(parsed.host)
        except ValueError:
            if parsed.host.lower().rstrip(".") in (
                "localhost",
                "localhost.localdomain",
            ):
                raise UnsafeDestination("Unsafe destination") from None
        else:
            if not _address_allowed(str(ip), trusted):
                raise UnsafeDestination("Unsafe destination")
        return parsed
    except (httpx.InvalidURL, ValueError) as exc:
        raise UnsafeDestination("Unsafe destination") from exc


def validate_trusted_origins(origins: list[str]) -> list[str]:
    normalized = []
    for origin in origins:
        try:
            parsed = httpx.URL(origin)
            ipaddress.ip_address(parsed.host)
            if (
                parsed.path not in ("", "/")
                or parsed.query
                or parsed.fragment
                or parsed.userinfo
            ):
                raise ValueError
            canonical = str(
                parsed.copy_with(path="/", query=None, fragment=None)
            ).rstrip("/")
            validate_destination(canonical, [canonical])
            normalized.append(canonical)
        except (httpx.InvalidURL, ValueError) as exc:
            raise ValueError(
                "Trusted destinations must be safe numeric HTTP origins"
            ) from exc
    return normalized


def pin_destination(url: str, trusted_origins: list[str]) -> tuple[httpx.URL, str, str]:
    parsed = validate_destination(url, trusted_origins)
    origin = str(parsed.copy_with(path="/", query=None, fragment=None)).rstrip("/")
    trusted = origin in trusted_origins
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = socket.getaddrinfo(parsed.host, port, type=socket.SOCK_STREAM)
    if not addresses or any(
        not _address_allowed(str(info[4][0]), trusted) for info in addresses
    ):
        raise UnsafeDestination("Unsafe destination")
    address = str(addresses[0][4][0])
    host_header = parsed.netloc.decode("ascii")
    return parsed.copy_with(host=address), host_header, parsed.host
