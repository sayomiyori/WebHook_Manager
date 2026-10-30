import pytest
from pydantic import ValidationError

from src.api.v1.schemas.auth import LoginRequest, RegisterRequest


def test_register_trims_email_and_preserves_case() -> None:
    request = RegisterRequest(email="  Mixed@Example.COM ", password="secret12")
    assert request.email == "Mixed@Example.COM"


@pytest.mark.parametrize("password", ["", "short", "x" * 73])
def test_register_rejects_invalid_password_length(password: str) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(email="user@example.com", password=password)


@pytest.mark.parametrize("password", ["secret", "x" * 72, "П" * 6, "П" * 36])
def test_register_accepts_password_byte_boundaries(password: str) -> None:
    assert RegisterRequest(email="user@example.com", password=password).password


def test_register_rejects_short_multibyte_and_overlong_password() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(email="user@example.com", password="ППП")
    with pytest.raises(ValidationError):
        RegisterRequest(email="user@example.com", password="П" * 37)


@pytest.mark.parametrize(
    "email",
    ["", "no-at", "a@b", "a b@example.com", "a@b..c", "a@-b.c", ".@b.c", "a@b.c."],
)
def test_register_rejects_invalid_email(email: str) -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(email=email, password="secret12")


def test_login_keeps_short_wrong_password_and_trims_email() -> None:
    request = LoginRequest(email=" User@Example.COM ", password="wrong")
    assert request.email == "User@Example.COM"
    assert request.password == "wrong"


@pytest.mark.parametrize("email", ["root@localhost", "admin", "user@münchen.de"])
def test_login_accepts_legacy_nonconforming_identifier(email: str) -> None:
    assert LoginRequest(email=email, password="wrong").email == email


@pytest.mark.parametrize("password", ["", "x" * 73, "П" * 37])
def test_login_rejects_empty_or_oversized_password(password: str) -> None:
    with pytest.raises(ValidationError):
        LoginRequest(email="user@example.com", password=password)
