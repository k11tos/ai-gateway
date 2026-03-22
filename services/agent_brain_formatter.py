from typing import Literal
from typing import Protocol
from typing import TypedDict

WARNING_THRESHOLD_PERCENT = 90.0


class AgentBrainSummaryLike(Protocol):
    gateway: str
    disk_percent: float | None
    memory_percent: float | None
    load_average: list[float] | None


class AgentBrainPresentation(TypedDict):
    overall_status: Literal['ok', 'partial', 'warning']
    message_lines: list[str]


def format_agent_brain_summary(
    summary: AgentBrainSummaryLike,
) -> AgentBrainPresentation:
    overall_status = _overall_status(summary)

    return {
        'overall_status': overall_status,
        'message_lines': _message_lines(summary, overall_status=overall_status),
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
    return any(
        value is not None and value >= WARNING_THRESHOLD_PERCENT
        for value in (summary.disk_percent, summary.memory_percent)
    )


def _has_missing_metric(summary: AgentBrainSummaryLike) -> bool:
    return (
        summary.disk_percent is None
        or summary.memory_percent is None
        or summary.load_average is None
    )


def _message_lines(
    summary: AgentBrainSummaryLike,
    *,
    overall_status: Literal['ok', 'partial', 'warning'],
) -> list[str]:
    lines = [_gateway_line(summary.gateway, overall_status=overall_status)]
    lines.append(_disk_line(summary.disk_percent))
    lines.append(_memory_line(summary.memory_percent))
    lines.append(_load_average_line(summary.load_average))
    lines.append(_action_line(overall_status))
    return lines


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


def _action_line(overall_status: Literal['ok', 'partial', 'warning']) -> str:
    if overall_status == 'warning':
        return '자원 사용률이 높아 즉시 점검이 필요합니다.'

    if overall_status == 'partial':
        return '일부 지표가 없어 추가 확인이 필요합니다.'

    return '현재 즉시 대응이 필요한 징후는 없습니다.'
