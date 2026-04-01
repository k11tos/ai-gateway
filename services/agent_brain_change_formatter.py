from typing import Literal
from typing import Protocol
from typing import TypedDict

WARNING_THRESHOLD_PERCENT = 90.0


class AgentBrainChangeLike(TypedDict):
    kind: Literal[
        'metric_delta',
        'service_state_change',
        'docker_summary_change',
        'restart_detected',
    ]
    field: str
    previous: float | int | str | None | dict[str, int]
    current: float | int | str | None | dict[str, int]
    notable: bool


class AgentBrainChangesPresentation(TypedDict):
    has_notable_changes: bool
    changes: list[AgentBrainChangeLike]


class MetricDeltaLike(Protocol):
    name: str
    previous: float
    current: float


class ServiceStateChangeLike(Protocol):
    service_name: str
    previous_state: str | None
    current_state: str | None


class DockerSummaryChangeLike(Protocol):
    previous_running: int
    current_running: int
    previous_stopped: int
    current_stopped: int


class AgentBrainChangeSetLike(Protocol):
    has_previous_snapshot: bool
    restart_detected: bool
    previous_uptime_seconds: float | None
    current_uptime_seconds: float | None
    metric_deltas: list[MetricDeltaLike]
    service_state_changes: list[ServiceStateChangeLike]
    docker_summary_change: DockerSummaryChangeLike | None


def format_agent_brain_changes(change_set: AgentBrainChangeSetLike) -> AgentBrainChangesPresentation:
    if not change_set.has_previous_snapshot:
        return {
            'has_notable_changes': False,
            'changes': [],
        }

    changes: list[AgentBrainChangeLike] = []

    for delta in change_set.metric_deltas:
        notable = _is_notable_metric_delta(delta)
        changes.append(
            {
                'kind': 'metric_delta',
                'field': delta.name,
                'previous': delta.previous,
                'current': delta.current,
                'notable': notable,
            }
        )

    for service_change in change_set.service_state_changes:
        notable = _is_notable_service_state_change(service_change)
        changes.append(
            {
                'kind': 'service_state_change',
                'field': f'service_states.{service_change.service_name}',
                'previous': service_change.previous_state,
                'current': service_change.current_state,
                'notable': notable,
            }
        )

    if change_set.docker_summary_change is not None:
        notable = _is_notable_docker_summary_change(change_set.docker_summary_change)
        changes.append(
            {
                'kind': 'docker_summary_change',
                'field': 'docker_summary',
                'previous': {
                    'running': change_set.docker_summary_change.previous_running,
                    'stopped': change_set.docker_summary_change.previous_stopped,
                },
                'current': {
                    'running': change_set.docker_summary_change.current_running,
                    'stopped': change_set.docker_summary_change.current_stopped,
                },
                'notable': notable,
            }
        )

    if (
        change_set.restart_detected
        and change_set.previous_uptime_seconds is not None
        and change_set.current_uptime_seconds is not None
    ):
        changes.append(
            {
                'kind': 'restart_detected',
                'field': 'uptime_seconds',
                'previous': change_set.previous_uptime_seconds,
                'current': change_set.current_uptime_seconds,
                'notable': True,
            }
        )

    return {
        'has_notable_changes': any(change['notable'] for change in changes),
        'changes': changes,
    }


def _is_notable_metric_delta(delta: MetricDeltaLike) -> bool:
    if delta.name in {'disk_percent', 'memory_percent'}:
        worsened = delta.current > delta.previous
        entered_warning = delta.current >= WARNING_THRESHOLD_PERCENT and delta.previous < WARNING_THRESHOLD_PERCENT
        return worsened or entered_warning

    if delta.name == 'load_average':
        return delta.current > delta.previous

    return True


_SERVICE_STATE_SCORES: dict[str | None, int] = {
    'active': 3,
    'activating': 2,
    'reloading': 2,
    'deactivating': 1,
    'inactive': 0,
    'failed': -1,
    None: 0,
}


def _is_notable_service_state_change(service_change: ServiceStateChangeLike) -> bool:
    previous_score = _SERVICE_STATE_SCORES.get(service_change.previous_state, 0)
    current_score = _SERVICE_STATE_SCORES.get(service_change.current_state, 0)
    return current_score < previous_score


def _is_notable_docker_summary_change(docker_change: DockerSummaryChangeLike) -> bool:
    return (
        docker_change.current_running < docker_change.previous_running
        or docker_change.current_stopped > docker_change.previous_stopped
    )
