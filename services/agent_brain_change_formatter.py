from typing import Literal
from typing import Protocol
from typing import TypedDict


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
        changes.append(
            {
                'kind': 'metric_delta',
                'field': delta.name,
                'previous': delta.previous,
                'current': delta.current,
                'notable': True,
            }
        )

    for service_change in change_set.service_state_changes:
        changes.append(
            {
                'kind': 'service_state_change',
                'field': f'service_states.{service_change.service_name}',
                'previous': service_change.previous_state,
                'current': service_change.current_state,
                'notable': True,
            }
        )

    if change_set.docker_summary_change is not None:
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
                'notable': True,
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
        'has_notable_changes': len(changes) > 0,
        'changes': changes,
    }
