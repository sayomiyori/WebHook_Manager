from __future__ import annotations

from src.domain.entities.api_key import ApiKey
from src.domain.entities.delivery import DeliveryAttempt
from src.domain.entities.endpoint import Endpoint
from src.domain.entities.source import Source
from src.domain.entities.subscription import Subscription
from src.domain.entities.user import User
from src.domain.entities.webhook_event import WebhookEvent
from src.infrastructure.db.models.api_key import ApiKeyModel
from src.infrastructure.db.models.delivery_attempt import DeliveryAttemptModel
from src.infrastructure.db.models.endpoint import EndpointModel
from src.infrastructure.db.models.source import SourceModel
from src.infrastructure.db.models.subscription import SubscriptionModel
from src.infrastructure.db.models.user import UserModel
from src.infrastructure.db.models.webhook_event import WebhookEventModel


def user_to_entity(model: UserModel) -> User:
    return User(
        id=model.id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        email=model.email,
        hashed_password=model.hashed_password,
        is_active=model.is_active,
    )


def user_to_model(entity: User) -> UserModel:
    return UserModel(
        id=entity.id,
        email=entity.email,
        hashed_password=entity.hashed_password,
        is_active=entity.is_active,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def api_key_to_entity(model: ApiKeyModel) -> ApiKey:
    return ApiKey(
        id=model.id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        key_prefix=model.key_prefix,
        key_hash=model.key_hash,
        name=model.name,
        owner_id=model.owner_id,
        last_used_at=model.last_used_at,
        is_active=model.is_active,
    )


def api_key_to_model(entity: ApiKey) -> ApiKeyModel:
    return ApiKeyModel(
        id=entity.id,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        key_prefix=entity.key_prefix,
        key_hash=entity.key_hash,
        name=entity.name,
        owner_id=entity.owner_id,
        last_used_at=entity.last_used_at,
        is_active=entity.is_active,
    )


def source_to_entity(model: SourceModel) -> Source:
    return Source(
        id=model.id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        name=model.name,
        slug=model.slug,
        owner_id=model.owner_id,
        secret=model.secret,
        is_active=model.is_active,
    )


def source_to_model(entity: Source) -> SourceModel:
    return SourceModel(
        id=entity.id,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        name=entity.name,
        slug=entity.slug,
        owner_id=entity.owner_id,
        secret=entity.secret,
        is_active=entity.is_active,
    )


def endpoint_to_entity(model: EndpointModel) -> Endpoint:
    return Endpoint(
        id=model.id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        name=model.name,
        url=model.url,
        owner_id=model.owner_id,
        secret=model.secret,
        is_active=model.is_active,
        failure_count=model.failure_count,
    )


def endpoint_to_model(entity: Endpoint) -> EndpointModel:
    return EndpointModel(
        id=entity.id,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        name=entity.name,
        url=entity.url,
        owner_id=entity.owner_id,
        secret=entity.secret,
        is_active=entity.is_active,
        failure_count=entity.failure_count,
    )


def subscription_to_entity(model: SubscriptionModel) -> Subscription:
    return Subscription(
        id=model.id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        endpoint_id=model.endpoint_id,
        source_id=model.source_id,
        owner_id=model.owner_id,
        event_type_filter=list(model.event_type_filter),
        is_active=model.is_active,
    )


def subscription_to_model(entity: Subscription) -> SubscriptionModel:
    return SubscriptionModel(
        id=entity.id,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        endpoint_id=entity.endpoint_id,
        source_id=entity.source_id,
        owner_id=entity.owner_id,
        event_type_filter=list(entity.event_type_filter),
        is_active=entity.is_active,
    )


def webhook_event_to_entity(model: WebhookEventModel) -> WebhookEvent:
    return WebhookEvent(
        id=model.id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        source_id=model.source_id,
        payload=dict(model.payload),
        headers=dict(model.headers),
        idempotency_key=model.idempotency_key,
        event_type=model.event_type,
        received_at=model.received_at,
    )


def webhook_event_to_model(entity: WebhookEvent) -> WebhookEventModel:
    return WebhookEventModel(
        id=entity.id,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        source_id=entity.source_id,
        payload=dict(entity.payload),
        headers=dict(entity.headers),
        idempotency_key=entity.idempotency_key,
        event_type=entity.event_type,
        received_at=entity.received_at,
    )


def delivery_attempt_to_entity(model: DeliveryAttemptModel) -> DeliveryAttempt:
    return DeliveryAttempt(
        id=model.id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        event_id=model.event_id,
        endpoint_id=model.endpoint_id,
        attempt_number=model.attempt_number,
        status=model.status,
        response_code=model.response_code,
        response_body=model.response_body,
        error_message=model.error_message,
        attempted_at=model.attempted_at,
    )


def delivery_attempt_to_model(entity: DeliveryAttempt) -> DeliveryAttemptModel:
    return DeliveryAttemptModel(
        id=entity.id,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
        event_id=entity.event_id,
        endpoint_id=entity.endpoint_id,
        attempt_number=entity.attempt_number,
        status=entity.status,
        response_code=entity.response_code,
        response_body=entity.response_body,
        error_message=entity.error_message,
        attempted_at=entity.attempted_at,
    )

