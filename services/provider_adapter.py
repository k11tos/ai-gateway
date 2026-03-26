from dataclasses import dataclass
from typing import Callable, Protocol


class ProviderAdapter(Protocol):
    def generate(self, *, prompt: str, model: str) -> str: ...

    def generate_stream(self, *, prompt: str, model: str): ...

    def list_models(self) -> list[str]: ...

    def embedding(self, *, text: str) -> list[float]: ...


@dataclass(frozen=True)
class CallableProviderAdapter:
    generate_fn: Callable[..., str]
    generate_stream_fn: Callable[..., object]
    list_models_fn: Callable[[], list[str]]
    embedding_fn: Callable[[str], list[float]]

    def generate(self, *, prompt: str, model: str) -> str:
        return self.generate_fn(prompt=prompt, model=model)

    def generate_stream(self, *, prompt: str, model: str):
        return self.generate_stream_fn(prompt=prompt, model=model)

    def list_models(self) -> list[str]:
        return self.list_models_fn()

    def embedding(self, *, text: str) -> list[float]:
        return self.embedding_fn(text)
