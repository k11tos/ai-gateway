import pytest
from fastapi import HTTPException

from services import presets


EXPECTED_PRESETS_CONTRACT = [
    {
        "name": "normal",
        "description": "Balanced assistant for general use.",
        "prompt_prefix": "",
    },
    {
        "name": "coder",
        "description": "Focused on programming and debugging tasks.",
        "prompt_prefix": "You are a practical coding assistant. Be precise and production-minded.\n\n",
    },
    {
        "name": "english",
        "description": "Helps improve English writing and grammar.",
        "prompt_prefix": "You are an English writing helper. Improve clarity, grammar, and tone.\n\n",
    },
    {
        "name": "quant",
        "description": "Supports quantitative and analytical reasoning.",
        "prompt_prefix": "You are a quantitative reasoning assistant. Show concise, correct math.\n\n",
    },
]


def test_presets_endpoint_contract_shape_order_and_content(client):
    response = client.get("/presets")

    assert response.status_code == 200
    assert response.json() == {"presets": EXPECTED_PRESETS_CONTRACT}


def test_presets_endpoint_presets_have_required_string_fields(client):
    response = client.get("/presets")

    assert response.status_code == 200
    payload = response.json()

    assert set(payload.keys()) == {"presets"}
    assert isinstance(payload["presets"], list)

    for preset in payload["presets"]:
        assert set(preset.keys()) == {"name", "description", "prompt_prefix"}
        assert isinstance(preset["name"], str) and preset["name"]
        assert isinstance(preset["description"], str) and preset["description"]
        assert isinstance(preset["prompt_prefix"], str)


def test_preset_service_apply_prompt_preset_for_known_preset_uses_prefix():
    prompt = "Write a unit test"

    shaped = presets.apply_prompt_preset(prompt, "coder")

    assert shaped == (
        "You are a practical coding assistant. Be precise and production-minded.\n\n"
        "Write a unit test"
    )


def test_preset_service_apply_prompt_preset_for_unknown_preset_raises_400():
    with pytest.raises(HTTPException) as exc_info:
        presets.apply_prompt_preset("hello", "unknown")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == (
        "Unknown preset 'unknown'. Valid presets: normal, coder, english, quant"
    )


def test_preset_service_apply_prompt_preset_accepts_normalized_input():
    shaped = presets.apply_prompt_preset("hello", " CODER ")

    assert shaped == presets.PRESET_BY_NAME["coder"]["prompt_prefix"] + "hello"


def test_preset_service_list_presets_contract_is_stable():
    listed_presets = presets.list_presets()

    assert listed_presets == EXPECTED_PRESETS_CONTRACT
    assert [preset["name"] for preset in listed_presets] == [
        "normal",
        "coder",
        "english",
        "quant",
    ]
    assert all(
        set(preset.keys()) == {"name", "description", "prompt_prefix"}
        for preset in listed_presets
    )
