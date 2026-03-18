from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from src.domain.entities.api_key import ApiKey
from src.domain.entities.delivery import DeliveryAttempt
from src.domain.entities.endpoint import Endpoint
from src.domain.entities.source import Source
from src.domain.entities.subscription import Subscription
from src.domain.entities.user import User
from src.domain.entities.webhook_event import WebhookEvent


class UserRepository(ABC):
    @abstractmethod
    async def get_by_id(self, id: UUID) -> User | None: ...

    @abstractmethod
    async def get_by_email(self, email: str) -> User | None: ...

    @abstractmethod
    async def create(self, user: User) -> User: ...

    @abstractmethod
    async def update(self, user: User) -> User: ...

    @abstractmethod
    async def delete(self, id: UUID) -> None: ...


class ApiKeyRepository(ABC):
    @abstractmethod
    async def get_by_id(self, id: UUID) -> ApiKey | None: ...

    @abstractmethod
    async def get_by_owner(
        self, owner_id: UUID, cursor: UUID | None, limit: int
    ) -> list[ApiKey]: ...

    @abstractmethod
    async def get_by_prefix(self, key_prefix: str) -> ApiKey | None: ...

    @abstractmethod
    async def create(self, api_key: ApiKey) -> ApiKey: ...

    @abstractmethod
    async def update(self, api_key: ApiKey) -> ApiKey: ...

    @abstractmethod
    async def delete(self, id: UUID) -> None: ...


class SourceRepository(ABC):
    @abstractmethod
    async def get_by_id(self, id: UUID) -> Source | None: ...

    @abstractmethod
    async def get_by_owner(
        self, owner_id: UUID, cursor: UUID | None, limit: int
    ) -> list[Source]: ...

    @abstractmethod
    async def get_by_slug(self, owner_id: UUID, slug: str) -> Source | None: ...

    @abstractmethod
    async def get_by_slug_global(self, slug: str) -> Source | None: ...

    @abstractmethod
    async def create(self, source: Source) -> Source: ...

    @abstractmethod
    async def update(self, source: Source) -> Source: ...

    @abstractmethod
    async def delete(self, id: UUID) -> None: ...


class EndpointRepository(ABC):
    @abstractmethod
    async def get_by_id(self, id: UUID) -> Endpoint | None: ...

    @abstractmethod
    async def get_by_owner(
        self, owner_id: UUID, cursor: UUID | None, limit: int
    ) -> list[Endpoint]: ...

    @abstractmethod
    async def create(self, endpoint: Endpoint) -> Endpoint: ...

    @abstractmethod
    async def update(self, endpoint: Endpoint) -> Endpoint: ...

    @abstractmethod
    async def delete(self, id: UUID) -> None: ...


class SubscriptionRepository(ABC):
    @abstractmethod
    async def get_by_id(self, id: UUID) -> Subscription | None: ...

    @abstractmethod
    async def get_by_owner(
        self, owner_id: UUID, cursor: UUID | None, limit: int
    ) -> list[Subscription]: ...

    @abstractmethod
    async def get_by_endpoint(
        self, endpoint_id: UUID, cursor: UUID | None, limit: int
    ) -> list[Subscription]: ...

    @abstractmethod
    async def get_by_source(
        self, source_id: UUID, cursor: UUID | None, limit: int
    ) -> list[Subscription]: ...

    @abstractmethod
    async def create(self, subscription: Subscription) -> Subscription: ...

    @abstractmethod
    async def update(self, subscription: Subscription) -> Subscription: ...

    @abstractmethod
    async def delete(self, id: UUID) -> None: ...


class WebhookEventRepository(ABC):
    @abstractmethod
    async def get_by_id(self, id: UUID) -> WebhookEvent | None: ...

    @abstractmethod
    async def get_by_owner(
        self, owner_id: UUID, cursor: UUID | None, limit: int
    ) -> list[WebhookEvent]: ...

    @abstractmethod
    async def get_by_source(
        self, source_id: UUID, cursor: UUID | None, limit: int
    ) -> list[WebhookEvent]: ...

    @abstractmethod
    async def get_by_idempotency_key(
        self, source_id: UUID, idempotency_key: str
    ) -> WebhookEvent | None: ...

    @abstractmethod
    async def create(self, event: WebhookEvent) -> WebhookEvent: ...

    @abstractmethod
    async def update(self, event: WebhookEvent) -> WebhookEvent: ...

    @abstractmethod
    async def delete(self, id: UUID) -> None: ...


class DeliveryAttemptRepository(ABC):
    @abstractmethod
    async def get_by_id(self, id: UUID) -> DeliveryAttempt | None: ...

    @abstractmethod
    async def get_by_event(
        self, event_id: UUID, cursor: UUID | None, limit: int
    ) -> list[DeliveryAttempt]: ...

    @abstractmethod
    async def create(self, attempt: DeliveryAttempt) -> DeliveryAttempt: ...

    @abstractmethod
    async def update(self, attempt: DeliveryAttempt) -> DeliveryAttempt: ...

    @abstractmethod
    async def delete(self, id: UUID) -> None: ...


type EventRepository = WebhookEventRepository
type DeliveryRepository = DeliveryAttemptRepository

