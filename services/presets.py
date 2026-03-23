from fastapi import HTTPException

# Client-facing API contract for /presets. Keep names, descriptions, and order stable
# unless intentionally coordinating changes with downstream clients.
PRESET_DEFINITIONS = (
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
)
PRESET_BY_NAME = {preset["name"]: preset for preset in PRESET_DEFINITIONS}


def normalize_preset_name(preset: str | None) -> str | None:
    if preset is None:
        return None

    return preset.strip().lower()



def apply_prompt_preset(prompt: str, preset: str | None) -> str:
    normalized_preset = normalize_preset_name(preset)

    if normalized_preset is None:
        return prompt

    preset_config = PRESET_BY_NAME.get(normalized_preset)
    if preset_config is None:
        valid_presets = ", ".join(PRESET_BY_NAME)
        raise HTTPException(
            status_code=400,
            detail=f"Unknown preset '{preset}'. Valid presets: {valid_presets}",
        )

    return f"{preset_config['prompt_prefix']}{prompt}"



def list_presets() -> list[dict[str, str]]:
    return [
        {
            "name": preset["name"],
            "description": preset["description"],
            "prompt_prefix": preset["prompt_prefix"],
        }
        for preset in PRESET_DEFINITIONS
    ]
