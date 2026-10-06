from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.infrastructure.db.models.platform_ingress_outbox import (
    PlatformIngressOutboxModel,
)
from src.infrastructure.db.models.telegram_bot import TelegramBotModel
from src.infrastructure.db.models.telegram_ingress_event import (
    TelegramIngressEventModel,
)


async def test_ingress_and_outbox_identity_constraints(db_session):
    tenant, bot_id, event_id = uuid4(), uuid4(), uuid4()
    db_session.add(
        TelegramBotModel(
            id=bot_id,
            tenant_id=tenant,
            created_by=uuid4(),
            name="Storage test",
            telegram_bot_id=uuid4().int % 2**50,
            credentials_encrypted="fictional-ciphertext",
        )
    )
    await db_session.flush()
    event = TelegramIngressEventModel(
        id=event_id,
        tenant_id=tenant,
        bot_id=bot_id,
        update_id=17,
        raw={"update_id": 17},
        digest="a" * 64,
        state="ignored",
        correlation_id=uuid4(),
        envelope=None,
    )
    db_session.add(event)
    await db_session.flush()
    row = PlatformIngressOutboxModel(
        id=uuid4(), ingress_id=event_id, tenant_id=tenant, bot_id=bot_id
    )
    db_session.add(row)
    await db_session.flush()
    assert row.attempts == 0 and row.state == "pending"
    async with db_session.begin_nested() as nested:
        db_session.add(
            PlatformIngressOutboxModel(
                id=uuid4(), ingress_id=event_id, tenant_id=tenant, bot_id=bot_id
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await nested.rollback()
    assert (await db_session.scalar(select(PlatformIngressOutboxModel.id))) is not None


async def test_invalid_ingress_state_is_rejected(db_session):
    bot_id, tenant_id = uuid4(), uuid4()
    db_session.add(
        TelegramBotModel(
            id=bot_id,
            tenant_id=tenant_id,
            created_by=uuid4(),
            name="State test",
            telegram_bot_id=uuid4().int % 2**50,
            credentials_encrypted="fictional-ciphertext",
        )
    )
    await db_session.flush()
    async with db_session.begin_nested() as nested:
        db_session.add(
            TelegramIngressEventModel(
                id=uuid4(),
                tenant_id=tenant_id,
                bot_id=bot_id,
                update_id=0,
                raw={},
                digest="a" * 64,
                state="invalid",
                correlation_id=uuid4(),
            )
        )
        with pytest.raises(IntegrityError, match="ck_telegram_ingress_state"):
            await db_session.flush()
        await nested.rollback()
