from dataclasses import dataclass
from typing import Protocol

RESOURCE_CHANGE_THRESHOLD_PERCENT = 5.0
LOAD_AVERAGE_CHANGE_THRESHOLD = 0.5
UPTIME_RESTART_DROP_THRESHOLD_SECONDS = 300.0


class AgentBrainSnapshotLike(Protocol):
    disk_percent: float | None
    memory_percent: float | None
    load_average: list[float] | None
    uptime_seconds: float | None
    service_states: dict[str, str | None] | None
    docker_summary: dict[str, int] | None


@dataclass(frozen=True)
class MetricDelta:
    name: str
    previous: float
    current: float
    delta: float


@dataclass(frozen=True)
class ServiceStateChange:
    service_name: str
    previous_state: str | None
    current_state: str | None


@dataclass(frozen=True)
class DockerSummaryChange:
    previous_running: int
    current_running: int
    previous_stopped: int
    current_stopped: int


@dataclass(frozen=True)
class AgentBrainChangeSet:
    has_previous_snapshot: bool
    restart_detected: bool
    uptime_drop_seconds: float | None
    previous_uptime_seconds: float | None
    current_uptime_seconds: float | None
    metric_deltas: list[MetricDelta]
    service_state_changes: list[ServiceStateChange]
    docker_summary_change: DockerSummaryChange | None


def _no_previous_snapshot_changeset() -> AgentBrainChangeSet:
    return AgentBrainChangeSet(
        has_previous_snapshot=False,
        restart_detected=False,
        uptime_drop_seconds=None,
        previous_uptime_seconds=None,
        current_uptime_seconds=None,
        metric_deltas=[],
        service_state_changes=[],
        docker_summary_change=None,
    )


def detect_agent_brain_changes(
    previous: AgentBrainSnapshotLike | None,
    current: AgentBrainSnapshotLike,
) -> AgentBrainChangeSet:
    if previous is None:
        return _no_previous_snapshot_changeset()

    metric_deltas = _metric_deltas(previous, current)
    uptime_drop_seconds = _uptime_drop_seconds(previous, current)

    return AgentBrainChangeSet(
        has_previous_snapshot=True,
        restart_detected=(uptime_drop_seconds is not None and uptime_drop_seconds >= UPTIME_RESTART_DROP_THRESHOLD_SECONDS),
        uptime_drop_seconds=uptime_drop_seconds,
        previous_uptime_seconds=previous.uptime_seconds,
        current_uptime_seconds=current.uptime_seconds,
        metric_deltas=metric_deltas,
        service_state_changes=_service_state_changes(previous, current),
        docker_summary_change=_docker_summary_change(previous, current),
    )


def _metric_deltas(
    previous: AgentBrainSnapshotLike,
    current: AgentBrainSnapshotLike,
) -> list[MetricDelta]:
    deltas: list[MetricDelta] = []

    disk = _metric_delta(
        metric_name='disk_percent',
        previous=previous.disk_percent,
        current=current.disk_percent,
        threshold=RESOURCE_CHANGE_THRESHOLD_PERCENT,
    )
    if disk is not None:
        deltas.append(disk)

    memory = _metric_delta(
        metric_name='memory_percent',
        previous=previous.memory_percent,
        current=current.memory_percent,
        threshold=RESOURCE_CHANGE_THRESHOLD_PERCENT,
    )
    if memory is not None:
        deltas.append(memory)

    previous_load = _load_average_1m(previous.load_average)
    current_load = _load_average_1m(current.load_average)
    load_average = _metric_delta(
        metric_name='load_average',
        previous=previous_load,
        current=current_load,
        threshold=LOAD_AVERAGE_CHANGE_THRESHOLD,
    )
    if load_average is not None:
        deltas.append(load_average)

    return deltas


def _metric_delta(
    *,
    metric_name: str,
    previous: float | None,
    current: float | None,
    threshold: float,
) -> MetricDelta | None:
    if previous is None or current is None:
        return None

    delta = current - previous
    if abs(delta) < threshold:
        return None

    return MetricDelta(
        name=metric_name,
        previous=previous,
        current=current,
        delta=delta,
    )


def _uptime_drop_seconds(
    previous: AgentBrainSnapshotLike,
    current: AgentBrainSnapshotLike,
) -> float | None:
    if previous.uptime_seconds is None or current.uptime_seconds is None:
        return None

    if current.uptime_seconds >= previous.uptime_seconds:
        return None

    return previous.uptime_seconds - current.uptime_seconds


def _service_state_changes(
    previous: AgentBrainSnapshotLike,
    current: AgentBrainSnapshotLike,
) -> list[ServiceStateChange]:
    previous_states = previous.service_states
    current_states = current.service_states

    if previous_states is None or current_states is None:
        return []

    service_names = sorted(set(previous_states) | set(current_states))
    changes: list[ServiceStateChange] = []
    for service_name in service_names:
        previous_state = previous_states.get(service_name)
        current_state = current_states.get(service_name)
        if previous_state == current_state:
            continue

        changes.append(
            ServiceStateChange(
                service_name=service_name,
                previous_state=previous_state,
                current_state=current_state,
            )
        )

    return changes


def _docker_summary_change(
    previous: AgentBrainSnapshotLike,
    current: AgentBrainSnapshotLike,
) -> DockerSummaryChange | None:
    previous_docker = previous.docker_summary
    current_docker = current.docker_summary

    if previous_docker is None or current_docker is None:
        return None

    previous_running = previous_docker.get('running', 0)
    current_running = current_docker.get('running', 0)
    previous_stopped = previous_docker.get('stopped', 0)
    current_stopped = current_docker.get('stopped', 0)

    if previous_running == current_running and previous_stopped == current_stopped:
        return None

    return DockerSummaryChange(
        previous_running=previous_running,
        current_running=current_running,
        previous_stopped=previous_stopped,
        current_stopped=current_stopped,
    )


def _load_average_1m(load_average: list[float] | None) -> float | None:
    if not load_average:
        return None

    return load_average[0]
