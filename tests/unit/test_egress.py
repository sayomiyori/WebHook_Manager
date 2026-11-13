import socket

import pytest

from src.core.egress import (
    UnsafeDestination,
    pin_destination,
    validate_destination,
    validate_trusted_origins,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://10.0.0.1/x",
        "http://169.254.169.254/x",
        "http://[::1]/x",
        "http://[::ffff:127.0.0.1]/x",
        "http://0.0.0.0/x",
        "http://100.64.0.1/x",
        "http://[64:ff9b::a00:1]/x",
        "http://224.0.0.1/x",
        "http://localhost/x",
        "file:///etc/passwd",
        "http://user:password@example.com/x",
        "https://example.com/x#fragment",
        " https://example.com/x",
    ],
)
def test_unsafe_literal_destination_rejected(url):
    with pytest.raises(UnsafeDestination, match="Unsafe destination"):
        validate_destination(url, [])


def test_mixed_dns_answers_rejected_before_connection(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443)),
        ],
    )
    with pytest.raises(UnsafeDestination):
        pin_destination("https://example.com/hook", [])


def test_public_dns_is_pinned_with_original_host_and_sni(monkeypatch):
    resolver_calls = []

    def resolve(*args, **kwargs):
        resolver_calls.append(args)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    url, host, sni = pin_destination("https://example.com:8443/hook?q=1", [])
    assert str(url) == "https://93.184.216.34:8443/hook?q=1"
    assert host == "example.com:8443" and sni == "example.com"
    assert len(resolver_calls) == 1


def test_private_exception_requires_exact_numeric_origin():
    trusted = validate_trusted_origins(["http://127.0.0.1:6543"])
    assert str(validate_destination("http://127.0.0.1:6543/hook", trusted)).endswith(
        "/hook"
    )
    with pytest.raises(UnsafeDestination):
        validate_destination("http://127.0.0.1:6544/hook", trusted)
    for origin in (
        "http://localhost:6543",
        "http://169.254.169.254",
        "http://127.0.0.1/hook",
    ):
        with pytest.raises(ValueError):
            validate_trusted_origins([origin])
