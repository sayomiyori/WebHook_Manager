from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import bcrypt

from src.core.security import generate_api_key, hash_api_key
from src.domain.entities.api_key import ApiKey
from src.domain.entities.user import User
from src.domain.interfaces.repositories import ApiKeyRepository, UserRepository


def hash_password(password: str) -> str:
    """Hash password using bcrypt (raw bytes -> utf-8 string)."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


class AuthService:
    def __init__(self, api_keys: ApiKeyRepository, users: UserRepository) -> None:
        self._api_keys = api_keys
        self._users = users

    async def create_api_key(
        self, owner_id: UUID, name: str
    ) -> tuple[ApiKey, str]:
        """Returns (api_key_entity, plaintext) — plaintext is shown once."""
        now = datetime.now(UTC)
        plaintext, prefix, key_hash = generate_api_key()
        entity = ApiKey(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            key_prefix=prefix,
            key_hash=key_hash,
            name=name,
            owner_id=owner_id,
            last_used_at=None,
            is_active=True,
        )
        saved = await self._api_keys.create(entity)
        return saved, plaintext

    async def verify_api_key(self, plaintext_key: str) -> ApiKey | None:
        """Verify plaintext key using SHA-256 hash lookup."""
        if not plaintext_key:
            return None
        key_hash = hash_api_key(plaintext_key)
        api_key = await self._api_keys.get_by_hash(key_hash)
        if api_key is None or not api_key.is_active:
            return None
        return api_key

    async def mark_key_used(self, key_id: UUID) -> None:
        """Update last_used_at in a background task."""
        api_key = await self._api_keys.get_by_id(key_id)
        if api_key is None or not api_key.is_active:
            return
        api_key.last_used_at = datetime.now(UTC)
        api_key.updated_at = api_key.last_used_at
        await self._api_keys.update(api_key)

    async def revoke_api_key(self, key_id: UUID, owner_id: UUID) -> None:
        api_key = await self._api_keys.get_by_id(key_id)
        if api_key is None or api_key.owner_id != owner_id:
            return
        await self._api_keys.delete(key_id)

    async def list_api_keys(self, owner_id: UUID) -> list[ApiKey]:
        # Repository supports cursor pagination; we loop to return full list.
        items: list[ApiKey] = []
        cursor: UUID | None = None
        page_size = 100
        while True:
            chunk = await self._api_keys.get_by_owner(
                owner_id, cursor=cursor, limit=page_size
            )
            items.extend(chunk)
            if len(chunk) < page_size:
                return items
            cursor = chunk[-1].id

    async def register_user(self, email: str, password: str) -> User:
        existing = await self._users.get_by_email(email)
        if existing is not None:
            # Keep it simple for demo purposes.
            return existing
        now = datetime.now(UTC)
        user = User(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            email=email,
            hashed_password=hash_password(password),
            is_active=True,
        )
        return await self._users.create(user)

    async def login_user(self, email: str, password: str) -> User | None:
        user = await self._users.get_by_email(email)
        if user is None or not user.is_active:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    # Backwards-compatible wrappers (internal code may still use old names).
    async def generate_key(self, *, owner_id: UUID, name: str) -> tuple[ApiKey, str]:
        return await self.create_api_key(owner_id, name)

    async def revoke_key(self, api_key_id: UUID) -> None:
        api_key = await self._api_keys.get_by_id(api_key_id)
        if api_key is None:
            return
        await self.revoke_api_key(api_key_id, api_key.owner_id)

    async def list_keys(
        self, *, owner_id: UUID, cursor: UUID | None, limit: int
    ) -> list[ApiKey]:
        return await self._api_keys.get_by_owner(owner_id, cursor=cursor, limit=limit)

    async def verify_key(self, raw_key: str) -> User | None:
        api_key = await self.verify_api_key(raw_key)
        if api_key is None:
            return None
        return await self._users.get_by_id(api_key.owner_id)

