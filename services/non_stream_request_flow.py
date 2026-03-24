from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class NonStreamRequestMetadata:
    requested_model: str
    resolved_model: str
    normalized_preset: str | None
    observed_provider: str


def prepare_non_stream_request_metadata(
    *,
    model: str | None,
    provider: str | None,
    preset: str | None,
    endpoint: str,
    request_id: str,
    default_provider: str,
    resolve_model: Callable[..., tuple[str, str]],
    normalize_preset_name: Callable[[str | None], str | None],
) -> NonStreamRequestMetadata:
    requested_model, resolved_model = resolve_model(
        model,
        endpoint=endpoint,
        request_id=request_id,
    )

    normalized_preset = normalize_preset_name(preset)
    observed_provider = (
        provider.strip().lower() if isinstance(provider, str) else default_provider
    )

    return NonStreamRequestMetadata(
        requested_model=requested_model,
        resolved_model=resolved_model,
        normalized_preset=normalized_preset,
        observed_provider=observed_provider,
    )


def run_non_stream_generation(
    *,
    prompt: str,
    preset: str | None,
    requested_model: str,
    resolved_model: str,
    provider: str,
    request_id: str,
    apply_prompt_preset: Callable[[str, str | None], str],
    generate_response: Callable[..., dict],
) -> dict:
    shaped_prompt = apply_prompt_preset(prompt, preset)
    return generate_response(
        prompt=shaped_prompt,
        requested_model=requested_model,
        resolved_model=resolved_model,
        provider=provider,
        request_id=request_id,
    )
