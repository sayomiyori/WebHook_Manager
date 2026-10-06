from __future__ import annotations

import hashlib
import json
from typing import cast

from src.api.v1.schemas.telegram_ingress import TelegramMessagePayload

KINDS = {
    "message",
    "edited_message",
    "channel_post",
    "edited_channel_post",
    "business_connection",
    "business_message",
    "edited_business_message",
    "deleted_business_messages",
    "guest_message",
    "message_reaction",
    "message_reaction_count",
    "inline_query",
    "chosen_inline_result",
    "callback_query",
    "shipping_query",
    "pre_checkout_query",
    "purchased_paid_media",
    "poll",
    "poll_answer",
    "my_chat_member",
    "chat_member",
    "chat_join_request",
    "chat_boost",
    "removed_chat_boost",
    "managed_bot",
    "subscription",
    "stopped_message_generation",
}


def identifier(value: object, positive: bool = False) -> int:
    if (
        type(value) is not int
        or not -(2**63) <= value <= 2**63 - 1
        or (positive and value <= 0)
    ):
        raise ValueError("Invalid Telegram identifier")
    return value


def normalize_update(raw: dict[str, object]) -> TelegramMessagePayload | None:
    update_id = identifier(raw.get("update_id"))
    kinds = KINDS.intersection(raw)
    if len(kinds) > 1 or any(not isinstance(raw[kind], dict) for kind in kinds):
        raise ValueError("Invalid Telegram update")
    message = raw.get("message")
    if message is None:
        return None
    if not isinstance(message, dict) or not isinstance(message.get("chat"), dict):
        raise ValueError("Invalid Telegram message")
    message_id = identifier(message.get("message_id"), positive=True)
    chat = message["chat"]
    chat_id = identifier(chat.get("id"))
    chat_type = chat.get("type")
    if not isinstance(chat_type, str) or chat_type not in {
        "private",
        "group",
        "supergroup",
        "channel",
    }:
        raise ValueError("Invalid Telegram chat")
    text = message.get("text")
    if "text" in message and (not isinstance(text, str) or len(text) > 4096):
        raise ValueError("Invalid Telegram text")
    if chat["type"] != "private" or not isinstance(text, str) or not text.strip():
        return None
    return TelegramMessagePayload(
        update_id=update_id, message_id=message_id, chat_id=chat_id, question=text
    )


def canonical_digest(raw: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            raw,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def parse_update(body: bytes) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def constant(_: str) -> object:
        raise ValueError("Non-finite JSON number")

    value = json.loads(
        body.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant
    )
    if not isinstance(value, dict):
        raise ValueError("Update must be an object")
    return cast(dict[str, object], value)
