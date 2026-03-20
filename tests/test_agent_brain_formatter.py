from types import SimpleNamespace

from services.agent_brain_formatter import format_agent_brain_summary


def test_format_agent_brain_summary_returns_ok_messages():
    summary = SimpleNamespace(
        gateway='ok',
        disk_percent=71.2,
        memory_percent=53.4,
        load_average=[0.12, 0.20, 0.18],
    )

    presentation = format_agent_brain_summary(summary)

    assert presentation == {
        'overall_status': 'ok',
        'message_lines': [
            'ai-gateway 정상',
            '디스크 사용률 71.2%입니다.',
            '메모리 사용률 53.4%입니다.',
            '로드 평균 0.12, 0.20, 0.18입니다.',
            '현재 즉시 대응이 필요한 징후는 없습니다.',
        ],
    }


def test_format_agent_brain_summary_returns_partial_when_metric_is_missing():
    summary = SimpleNamespace(
        gateway='ok',
        disk_percent=None,
        memory_percent=53.4,
        load_average=[0.12, 0.20, 0.18],
    )

    presentation = format_agent_brain_summary(summary)

    assert presentation['overall_status'] == 'partial'
    assert presentation['message_lines'][0] == 'ai-gateway 일부 지표 확인 필요'
    assert presentation['message_lines'][-1] == '일부 지표가 없어 추가 확인이 필요합니다.'


def test_format_agent_brain_summary_returns_warning_when_usage_is_high():
    summary = SimpleNamespace(
        gateway='ok',
        disk_percent=71.2,
        memory_percent=90.0,
        load_average=[0.12, 0.20, 0.18],
    )

    presentation = format_agent_brain_summary(summary)

    assert presentation['overall_status'] == 'warning'
    assert presentation['message_lines'][0] == 'ai-gateway 주의'
    assert presentation['message_lines'][2] == '메모리 사용률 90.0%로 높습니다.'
    assert presentation['message_lines'][-1] == '자원 사용률이 높아 즉시 점검이 필요합니다.'
