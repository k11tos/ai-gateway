from copy import deepcopy
from typing import Protocol


class AgentBrainSnapshotLike(Protocol):
    gateway: str
    disk_percent: float | None
    memory_percent: float | None
    load_average: list[float] | None
    uptime_seconds: float | None
    service_states: dict[str, str | None] | None
    docker_summary: dict[str, int] | None


class InMemoryAgentBrainSnapshotStore:
    """Best-effort in-memory snapshot storage for /agent/brain."""

    def __init__(self) -> None:
        self._last_snapshot: AgentBrainSnapshotLike | None = None

    def get_last_snapshot(self) -> AgentBrainSnapshotLike | None:
        return deepcopy(self._last_snapshot)

    def set_last_snapshot(self, snapshot: AgentBrainSnapshotLike) -> None:
        self._last_snapshot = deepcopy(snapshot)

    def reset(self) -> None:
        self._last_snapshot = None


agent_brain_snapshot_store = InMemoryAgentBrainSnapshotStore()
