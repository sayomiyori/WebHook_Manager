from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from src.core.security import GeneratedApiKey, generate_api_key, sha256_hex
from src.domain.entities.api_key import ApiKey
from src.domain.entities.user import User
from src.domain.interfaces.repositories import ApiKeyRepository, UserRepository


class AuthService:
    def __init__(self, api_keys: ApiKeyRepository, users: UserRepository) -> None:
        self._api_keys = api_keys
        self._users = users

    async def generate_key(self, *, owner_id: UUID, name: str) -> tuple[ApiKey, str]:
        now = datetime.now(UTC)
        gen: GeneratedApiKey = generate_api_key()
        entity = ApiKey(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            key_prefix=gen.prefix,
            key_hash=gen.sha256_hex,
            name=name,
            owner_id=owner_id,
            last_used_at=None,
            is_active=True,
        )
        saved = await self._api_keys.create(entity)
        return saved, gen.raw

    async def revoke_key(self, api_key_id: UUID) -> None:
        await self._api_keys.delete(api_key_id)

    async def list_keys(
        self, *, owner_id: UUID, cursor: UUID | None, limit: int
    ) -> list[ApiKey]:
        return await self._api_keys.get_by_owner(owner_id, cursor, limit)

    async def verify_key(self, raw_key: str) -> User | None:
        if len(raw_key) < 8:
            return None
        prefix = raw_key[:8]
        api_key = await self._api_keys.get_by_prefix(prefix)
        if api_key is None or not api_key.is_active:
            return None
        if sha256_hex(raw_key) != api_key.key_hash:
            return None
        return await self._users.get_by_id(api_key.owner_id)

