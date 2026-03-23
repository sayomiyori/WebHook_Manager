from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest

from src.core.exceptions import ConflictError
from src.domain.entities.api_key import ApiKey
from src.domain.entities.user import User
from src.services.auth_service import AuthService, hash_password, verify_password


def _api_key(
    *,
    owner_id: UUID,
    is_active: bool = True,
    key_id: UUID | None = None,
) -> ApiKey:
    now = datetime.now(UTC)
    return ApiKey(
        id=key_id or uuid4(),
        created_at=now,
        updated_at=now,
        key_prefix="wh",
        key_hash="hash",
        name="k",
        owner_id=owner_id,
        last_used_at=None,
        is_active=is_active,
    )


@pytest.mark.asyncio
async def test_create_api_key_returns_plaintext_once() -> None:
    api_keys = Mock()
    users = Mock()

    created: ApiKey | None = None

    async def _create(entity: ApiKey) -> ApiKey:
        nonlocal created
        created = entity
        return entity

    api_keys.create = AsyncMock(side_effect=_create)

    svc = AuthService(api_keys, users)
    owner_id = uuid4()
    api_key, plaintext = await svc.create_api_key(owner_id=owner_id, name="n")

    assert created is not None
    assert api_key.id == created.id
    assert plaintext
    api_keys.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_verify_api_key_empty_returns_none() -> None:
    api_keys = Mock()
    api_keys.get_by_hash = AsyncMock()
    users = Mock()
    svc = AuthService(api_keys, users)

    assert await svc.verify_api_key("") is None
    api_keys.get_by_hash.assert_not_called()


@pytest.mark.asyncio
async def test_verify_api_key_not_found_returns_none() -> None:
    api_keys = Mock()
    api_keys.get_by_hash = AsyncMock(return_value=None)
    users = Mock()
    svc = AuthService(api_keys, users)

    assert await svc.verify_api_key("some") is None


@pytest.mark.asyncio
async def test_verify_api_key_inactive_returns_none() -> None:
    api_keys = Mock()
    owner_id = uuid4()
    inactive = _api_key(owner_id=owner_id, is_active=False)
    api_keys.get_by_hash = AsyncMock(return_value=inactive)
    users = Mock()
    svc = AuthService(api_keys, users)

    assert await svc.verify_api_key("some") is None


@pytest.mark.asyncio
async def test_verify_api_key_active_returns_entity() -> None:
    api_keys = Mock()
    owner_id = uuid4()
    active = _api_key(owner_id=owner_id, is_active=True)
    api_keys.get_by_hash = AsyncMock(return_value=active)
    users = Mock()
    svc = AuthService(api_keys, users)

    out = await svc.verify_api_key("some")
    assert out is not None
    assert out.id == active.id


@pytest.mark.asyncio
async def test_mark_key_used_noop_on_missing_or_inactive() -> None:
    api_keys = Mock()
    api_keys.get_by_id = AsyncMock(return_value=None)
    api_keys.update = AsyncMock()
    users = Mock()
    svc = AuthService(api_keys, users)

    await svc.mark_key_used(key_id=uuid4())
    api_keys.update.assert_not_called()

    inactive = _api_key(owner_id=uuid4(), is_active=False)
    api_keys.get_by_id = AsyncMock(return_value=inactive)
    await svc.mark_key_used(key_id=inactive.id)
    api_keys.update.assert_not_called()


@pytest.mark.asyncio
async def test_mark_key_used_updates_last_used_at() -> None:
    api_keys = Mock()
    owner_id = uuid4()
    key = _api_key(owner_id=owner_id, is_active=True)
    api_keys.get_by_id = AsyncMock(return_value=key)
    api_keys.update = AsyncMock(side_effect=lambda ent: ent)
    users = Mock()
    svc = AuthService(api_keys, users)

    assert key.last_used_at is None
    await svc.mark_key_used(key_id=key.id)
    api_keys.update.assert_awaited_once()


@pytest.mark.asyncio
async def test_revoke_api_key_noop_wrong_owner() -> None:
    api_keys = Mock()
    users = Mock()
    svc = AuthService(api_keys, users)
    key = _api_key(owner_id=uuid4())
    api_keys.get_by_id = AsyncMock(return_value=key)
    api_keys.delete = AsyncMock()

    await svc.revoke_api_key(key_id=key.id, owner_id=uuid4())
    api_keys.delete.assert_not_called()


@pytest.mark.asyncio
async def test_revoke_api_key_deletes_on_owner_match() -> None:
    api_keys = Mock()
    users = Mock()
    svc = AuthService(api_keys, users)
    owner_id = uuid4()
    key = _api_key(owner_id=owner_id)
    api_keys.get_by_id = AsyncMock(return_value=key)
    api_keys.delete = AsyncMock()

    await svc.revoke_api_key(key_id=key.id, owner_id=owner_id)
    api_keys.delete.assert_awaited_once_with(key.id)


@pytest.mark.asyncio
async def test_list_api_keys_paginates_until_final_chunk() -> None:
    api_keys = Mock()
    users = Mock()
    svc = AuthService(api_keys, users)
    owner_id = uuid4()

    page1 = [_api_key(owner_id=owner_id, key_id=UUID(int=i)) for i in range(1, 101)]
    page2 = [_api_key(owner_id=owner_id, key_id=UUID(int=999))]

    api_keys.get_by_owner = AsyncMock(side_effect=[page1, page2])
    out = await svc.list_api_keys(owner_id=owner_id)
    assert len(out) == 101
    assert api_keys.get_by_owner.await_count == 2


@pytest.mark.asyncio
async def test_register_user_duplicate_email_raises_conflict() -> None:
    api_keys = Mock()
    users = Mock()
    svc = AuthService(api_keys, users)
    existing = User(
        id=uuid4(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        email="a@b.com",
        hashed_password="x",
        is_active=True,
    )
    users.get_by_email = AsyncMock(return_value=existing)
    users.create = AsyncMock()

    with pytest.raises(ConflictError):
        await svc.register_user(email=existing.email, password="pw")
    users.create.assert_not_called()


@pytest.mark.asyncio
async def test_register_user_creates_and_hashes_password() -> None:
    api_keys = Mock()
    users = Mock()
    svc = AuthService(api_keys, users)
    users.get_by_email = AsyncMock(return_value=None)

    async def _create(entity: User) -> User:
        return entity

    users.create = AsyncMock(side_effect=_create)

    out = await svc.register_user(email="c@d.com", password="secret")
    assert out.hashed_password != "secret"
    assert verify_password("secret", out.hashed_password) is True


@pytest.mark.asyncio
async def test_login_user_branches() -> None:
    api_keys = Mock()
    users = Mock()
    svc = AuthService(api_keys, users)

    users.get_by_email = AsyncMock(return_value=None)
    assert await svc.login_user("e@f.com", "pw") is None

    users.get_by_email = AsyncMock(
        return_value=User(
            id=uuid4(),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            email="e@f.com",
            hashed_password="x",
            is_active=False,
        )
    )
    assert await svc.login_user("e@f.com", "pw") is None

    hashed = hash_password("secret")
    active_user = User(
        id=uuid4(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        email="e@f.com",
        hashed_password=hashed,
        is_active=True,
    )

    users.get_by_email = AsyncMock(return_value=active_user)
    assert await svc.login_user("e@f.com", "wrong") is None
    out = await svc.login_user("e@f.com", "secret")
    assert out is not None
    assert out.id == active_user.id


@pytest.mark.asyncio
async def test_wrappers_verify_key_list_keys_and_revoke_key() -> None:
    api_keys = Mock()
    users = Mock()
    svc = AuthService(api_keys, users)

    owner_id = uuid4()
    key_id = uuid4()
    key = _api_key(owner_id=owner_id, key_id=key_id)
    user = User(
        id=owner_id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        email="u@e.com",
        hashed_password="x",
        is_active=True,
    )

    api_keys.get_by_hash = AsyncMock(return_value=key)
    users.get_by_id = AsyncMock(return_value=user)

    out = await svc.verify_key("raw")
    assert out is not None
    assert out.id == owner_id

    items = [_api_key(owner_id=owner_id)]
    api_keys.get_by_owner = AsyncMock(return_value=items)
    out_keys = await svc.list_keys(owner_id=owner_id, cursor=None, limit=10)
    assert out_keys == items

    api_keys.get_by_id = AsyncMock(side_effect=[key, key])
    api_keys.delete = AsyncMock()
    await svc.revoke_key(api_key_id=key_id)
    api_keys.delete.assert_awaited_once_with(key_id)

