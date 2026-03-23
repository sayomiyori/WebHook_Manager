from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from src.core.exceptions import ForbiddenError, NotFoundError
from src.domain.entities.endpoint import Endpoint
from src.domain.interfaces.repositories import EndpointRepository


class EndpointService:
    def __init__(self, endpoint_repo: EndpointRepository) -> None:
        self._repo = endpoint_repo

    async def create_endpoint(
        self, owner_id: UUID, name: str, url: str, secret: str | None
    ) -> Endpoint:
        now = datetime.now(UTC)
        endpoint = Endpoint(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            name=name,
            url=url,
            owner_id=owner_id,
            secret=secret,
            is_active=True,
            failure_count=0,
        )
        return await self._repo.create(endpoint)

    async def get_endpoint(self, endpoint_id: UUID, owner_id: UUID) -> Endpoint:
        endpoint = await self._repo.get_by_id(endpoint_id)
        if endpoint is None:
            raise NotFoundError()
        if endpoint.owner_id != owner_id:
            raise ForbiddenError()
        return endpoint

    async def list_endpoints(
        self, owner_id: UUID, cursor: UUID | None, limit: int
    ) -> tuple[list[Endpoint], UUID | None]:
        items = await self._repo.get_by_owner(owner_id, cursor, limit)
        next_cursor = items[-1].id if len(items) == limit else None
        return items, next_cursor

    async def update_endpoint(
        self,
        endpoint_id: UUID,
        owner_id: UUID,
        **fields: object,
    ) -> Endpoint:
        endpoint = await self.get_endpoint(endpoint_id, owner_id)

        if "name" in fields:
            endpoint.name = str(fields["name"])
        if "url" in fields:
            endpoint.url = str(fields["url"])
        if "secret" in fields:
            secret_val = fields["secret"]
            endpoint.secret = None if secret_val is None else str(secret_val)
        if "is_active" in fields:
            endpoint.is_active = bool(fields["is_active"])

        endpoint.updated_at = datetime.now(UTC)
        return await self._repo.update(endpoint)

    async def delete_endpoint(self, endpoint_id: UUID, owner_id: UUID) -> None:
        _ = await self.get_endpoint(endpoint_id, owner_id)
        await self._repo.delete(endpoint_id)

    async def increment_failure(self, endpoint_id: UUID) -> Endpoint:
        endpoint = await self._repo.get_by_id(endpoint_id)
        if endpoint is None:
            raise NotFoundError()
        endpoint.failure_count += 1
        endpoint.updated_at = datetime.now(UTC)
        return await self._repo.update(endpoint)

    async def reset_failure_count(self, endpoint_id: UUID) -> None:
        endpoint = await self._repo.get_by_id(endpoint_id)
        if endpoint is None:
            raise NotFoundError()
        endpoint.failure_count = 0
        endpoint.updated_at = datetime.now(UTC)
        await self._repo.update(endpoint)

