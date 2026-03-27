from typing import Literal
from typing import Protocol
from typing import TypedDict

WARNING_THRESHOLD_PERCENT = 90.0


class AgentBrainSummaryLike(Protocol):
    gateway: str
    disk_percent: float | None
    memory_percent: float | None
    load_average: list[float] | None
    uptime_seconds: float | None
    service_states: dict[str, str | None] | None
    docker_summary: dict[str, int] | None


class AgentBrainPresentation(TypedDict):
    overall_status: Literal['ok', 'partial', 'warning']
    message_lines: list[str]


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


class AgentBrainChangesPresentationLike(Protocol):
    has_notable_changes: bool
    changes: list[AgentBrainChangeLike]


def format_agent_brain_summary(
    summary: AgentBrainSummaryLike,
    changes: AgentBrainChangesPresentationLike | None = None,
) -> AgentBrainPresentation:
    overall_status = _overall_status(summary)

    return {
        'overall_status': overall_status,
        'message_lines': _message_lines(summary, overall_status=overall_status, changes=changes),
    }


def _overall_status(
    summary: AgentBrainSummaryLike,
) -> Literal['ok', 'partial', 'warning']:
    # Keep this rule order aligned with the endpoint requirement:
    # 1) warning when disk or memory is >= 90
    # 2) partial when any metric is missing
    # 3) otherwise ok
    if _is_warning(summary):
        return 'warning'

    if _has_missing_metric(summary):
        return 'partial'

    return 'ok'


def _is_warning(summary: AgentBrainSummaryLike) -> bool:
    if _has_resource_warning(summary):
        return True

    return _has_service_warning(summary)


def _has_missing_metric(summary: AgentBrainSummaryLike) -> bool:
    return (
        summary.disk_percent is None
        or summary.memory_percent is None
        or summary.load_average is None
        or summary.uptime_seconds is None
    )


def _message_lines(
    summary: AgentBrainSummaryLike,
    *,
    overall_status: Literal['ok', 'partial', 'warning'],
    changes: AgentBrainChangesPresentationLike | None,
) -> list[str]:
    lines = [_gateway_line(summary.gateway, overall_status=overall_status)]
    lines.append(_disk_line(summary.disk_percent))
    lines.append(_memory_line(summary.memory_percent))
    lines.append(_load_average_line(summary.load_average))
    lines.append(_uptime_line(summary.uptime_seconds))
    lines.append(_service_states_line(summary.service_states))
    lines.append(_docker_line(summary.docker_summary))
    lines.append(_action_line(summary, overall_status=overall_status))
    lines.extend(_change_lines(changes))
    return lines


def _change_lines(changes: AgentBrainChangesPresentationLike | None) -> list[str]:
    if changes is None:
        return []

    has_notable_changes = (
        changes.get('has_notable_changes', False)
        if isinstance(changes, dict)
        else changes.has_notable_changes
    )
    if not has_notable_changes:
        return []

    change_items = changes.get('changes', []) if isinstance(changes, dict) else changes.changes

    restart_lines = []
    service_lines = []
    docker_lines = []
    resource_lines = []
    other_metric_lines = []

    for change in change_items:
        kind = change['kind']
        if kind == 'restart_detected':
            restart_lines.append('가동 시간이 급감해 재시작이 의심됩니다.')
            continue

        if kind == 'service_state_change':
            service_name = change['field'].removeprefix('service_states.')
            previous_state = _render_state(change['previous'])
            current_state = _render_state(change['current'])
            if current_state in {'failed', 'inactive'}:
                service_lines.append(f'경고: {service_name} 상태 {previous_state}→{current_state}.')
            else:
                service_lines.append(f'{service_name} 상태 변경 {previous_state}→{current_state}.')
            continue

        if kind == 'docker_summary_change':
            previous = change['previous'] if isinstance(change['previous'], dict) else {}
            current = change['current'] if isinstance(change['current'], dict) else {}
            previous_running = previous.get('running', 0)
            current_running = current.get('running', 0)
            previous_stopped = previous.get('stopped', 0)
            current_stopped = current.get('stopped', 0)
            docker_lines.append(
                f'Docker 변화: 실행 {previous_running}→{current_running}, 중지 {previous_stopped}→{current_stopped}.'
            )
            continue

        if kind == 'metric_delta':
            metric_line = _metric_change_line(change)
            if metric_line is None:
                continue
            if change['field'] in {'disk_percent', 'memory_percent'}:
                resource_lines.append(metric_line)
            else:
                other_metric_lines.append(metric_line)

    return restart_lines + service_lines + docker_lines + resource_lines + other_metric_lines


def _render_state(value: float | int | str | None | dict[str, int]) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return 'unknown'
    return str(value)


def _metric_change_line(change: AgentBrainChangeLike) -> str | None:
    previous = change['previous']
    current = change['current']
    if not isinstance(previous, (int, float)) or not isinstance(current, (int, float)):
        return None

    field = change['field']
    if field == 'disk_percent':
        return f'디스크 사용률 변화 {previous:.1f}%→{current:.1f}%.'
    if field == 'memory_percent':
        return f'메모리 사용률 변화 {previous:.1f}%→{current:.1f}%.'
    if field == 'load_average':
        return f'로드 평균(1분) 변화 {previous:.2f}→{current:.2f}.'

    return None


def _gateway_line(
    gateway: str,
    *,
    overall_status: Literal['ok', 'partial', 'warning'],
) -> str:
    gateway_status_map = {
        'ok': '정상',
        'partial': '일부 지표 확인 필요',
        'warning': '주의',
    }
    return f'ai-gateway {gateway_status_map[overall_status]}'


def _disk_line(disk_percent: float | None) -> str:
    if disk_percent is None:
        return '디스크 사용률을 확인할 수 없습니다.'

    if disk_percent >= WARNING_THRESHOLD_PERCENT:
        return f'디스크 사용률 {disk_percent:.1f}%로 높습니다.'

    return f'디스크 사용률 {disk_percent:.1f}%입니다.'


def _memory_line(memory_percent: float | None) -> str:
    if memory_percent is None:
        return '메모리 사용률을 확인할 수 없습니다.'

    if memory_percent >= WARNING_THRESHOLD_PERCENT:
        return f'메모리 사용률 {memory_percent:.1f}%로 높습니다.'

    return f'메모리 사용률 {memory_percent:.1f}%입니다.'


def _load_average_line(load_average: list[float] | None) -> str:
    if load_average is None:
        return '로드 평균을 확인할 수 없습니다.'

    rendered = ', '.join(f'{value:.2f}' for value in load_average)
    return f'로드 평균 {rendered}입니다.'


def _action_line(
    summary: AgentBrainSummaryLike,
    overall_status: Literal['ok', 'partial', 'warning'],
) -> str:
    if overall_status == 'warning':
        if _has_resource_warning(summary):
            return '자원 사용률이 높아 즉시 점검이 필요합니다.'

        if _has_service_warning(summary):
            return '서비스 상태 경고가 감지되어 즉시 점검이 필요합니다.'

        return '자원 사용률이 높아 즉시 점검이 필요합니다.'

    if overall_status == 'partial':
        return '일부 지표가 없어 추가 확인이 필요합니다.'

    return '현재 즉시 대응이 필요한 징후는 없습니다.'


def _has_resource_warning(summary: AgentBrainSummaryLike) -> bool:
    return any(
        value is not None and value >= WARNING_THRESHOLD_PERCENT
        for value in (summary.disk_percent, summary.memory_percent)
    )


def _has_service_warning(summary: AgentBrainSummaryLike) -> bool:
    if not summary.service_states:
        return False

    return any(state in {'failed', 'inactive'} for state in summary.service_states.values())


def _uptime_line(uptime_seconds: float | None) -> str:
    if uptime_seconds is None:
        return '가동 시간을 확인할 수 없습니다.'

    total_seconds = max(0, int(uptime_seconds))
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _seconds = divmod(rem, 60)

    if days > 0:
        return f'가동 시간 {days}일 {hours}시간입니다.'
    if hours > 0:
        return f'가동 시간 {hours}시간 {minutes}분입니다.'
    return f'가동 시간 {minutes}분입니다.'


def _service_states_line(service_states: dict[str, str | None] | None) -> str:
    if service_states is None:
        return 'systemd 서비스 상태를 확인할 수 없습니다.'

    rendered_states = []
    for service_name in ('ai-gateway', 'telegram-bot'):
        state = service_states.get(service_name)
        state_text = state if state is not None else 'unknown'
        rendered_states.append(f'{service_name}={state_text}')

    rendered = ', '.join(rendered_states)
    return f'서비스 상태 {rendered}.'


def _docker_line(docker_summary: dict[str, int] | None) -> str:
    if docker_summary is None:
        return 'Docker 상태를 확인할 수 없습니다.'

    running = docker_summary.get('running', 0)
    stopped = docker_summary.get('stopped', 0)
    return f'Docker 컨테이너 실행 {running}개, 중지 {stopped}개입니다.'
