import pytest

from src.infrastructure.platform.telegram_update import (
    canonical_digest,
    normalize_update,
)


def update():
    return {
        "update_id": 17,
        "message": {
            "message_id": 3,
            "chat": {"id": 2**40, "type": "private"},
            "text": "  Hello 🦊  ",
        },
    }


def test_normalize_preserves_text_and_large_ids():
    result = normalize_update(update())
    assert result.question == "  Hello 🦊  " and result.chat_id == 2**40
    assert set(result.model_dump()) == {
        "update_id",
        "chat_id",
        "message_id",
        "question",
    }


@pytest.mark.parametrize("chat_type", [[], {}, None, True, 1, "unknown"])
def test_malformed_chat_type_is_a_validation_error(chat_type):
    raw = update()
    raw["message"]["chat"]["type"] = chat_type
    with pytest.raises(ValueError, match="Invalid Telegram chat"):
        normalize_update(raw)


@pytest.mark.parametrize("value", [True, "17", 2**63, -(2**63) - 1, None])
def test_update_ids_are_strict_signed64(value):
    raw = update()
    raw["update_id"] = value
    with pytest.raises(ValueError):
        normalize_update(raw)


def test_unsupported_updates_are_ignored_and_semantic_digest_is_stable():
    assert normalize_update({"update_id": 17, "callback_query": {"id": "17"}}) is None
    raw = update()
    raw["message"]["chat"]["type"] = "group"
    assert normalize_update(raw) is None
    assert canonical_digest({"a": 1, "b": {"c": 2}}) == canonical_digest(
        {"b": {"c": 2}, "a": 1}
    )
    assert canonical_digest({"a": 1}) != canonical_digest({"a": 2})
    raw = update()
    raw["edited_message"] = raw["message"]
    with pytest.raises(ValueError):
        normalize_update(raw)
