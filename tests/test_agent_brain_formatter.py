from types import SimpleNamespace

from services.agent_brain_formatter import format_agent_brain_summary


def test_format_agent_brain_summary_returns_ok_messages():
    summary = SimpleNamespace(
        gateway='ok',
        disk_percent=71.2,
        memory_percent=53.4,
        load_average=[0.12, 0.20, 0.18],
        uptime_seconds=3723.0,
        service_states={'ai-gateway': 'active', 'telegram-bot': 'active'},
        docker_summary={'running': 2, 'stopped': 1},
    )

    presentation = format_agent_brain_summary(summary)

    assert presentation == {
        'overall_status': 'ok',
        'message_lines': [
            'ai-gateway 정상',
            '디스크 사용률 71.2%입니다.',
            '메모리 사용률 53.4%입니다.',
            '로드 평균 0.12, 0.20, 0.18입니다.',
            '가동 시간 1시간 2분입니다.',
            '서비스 상태 ai-gateway=active, telegram-bot=active.',
            'Docker 컨테이너 실행 2개, 중지 1개입니다.',
            '현재 즉시 대응이 필요한 징후는 없습니다.',
        ],
    }


def test_format_agent_brain_summary_returns_partial_when_metric_is_missing():
    summary = SimpleNamespace(
        gateway='ok',
        disk_percent=None,
        memory_percent=53.4,
        load_average=[0.12, 0.20, 0.18],
        uptime_seconds=None,
        service_states={'ai-gateway': 'active', 'telegram-bot': 'active'},
        docker_summary=None,
    )

    presentation = format_agent_brain_summary(summary)

    assert presentation['overall_status'] == 'partial'
    assert presentation['message_lines'][0] == 'ai-gateway 일부 지표 확인 필요'
    assert presentation['message_lines'][4] == '가동 시간을 확인할 수 없습니다.'
    assert presentation['message_lines'][-1] == '일부 지표가 없어 추가 확인이 필요합니다.'


def test_format_agent_brain_summary_returns_warning_when_usage_is_high():
    summary = SimpleNamespace(
        gateway='ok',
        disk_percent=71.2,
        memory_percent=90.0,
        load_average=[0.12, 0.20, 0.18],
        uptime_seconds=3600.0,
        service_states={'ai-gateway': 'active', 'telegram-bot': 'active'},
        docker_summary={'running': 1, 'stopped': 0},
    )

    presentation = format_agent_brain_summary(summary)

    assert presentation['overall_status'] == 'warning'
    assert presentation['message_lines'][0] == 'ai-gateway 주의'
    assert presentation['message_lines'][2] == '메모리 사용률 90.0%로 높습니다.'
    assert presentation['message_lines'][-1] == '자원 사용률이 높아 즉시 점검이 필요합니다.'


def test_format_agent_brain_summary_keeps_warning_precedence_over_missing_metrics():
    summary = SimpleNamespace(
        gateway='ok',
        disk_percent=95.0,
        memory_percent=None,
        load_average=[0.12, 0.20, 0.18],
        uptime_seconds=3600.0,
        service_states={'ai-gateway': 'active', 'telegram-bot': 'active'},
        docker_summary={'running': 0, 'stopped': 0},
    )

    presentation = format_agent_brain_summary(summary)

    assert presentation['overall_status'] == 'warning'
    assert presentation['message_lines'] == [
        'ai-gateway 주의',
        '디스크 사용률 95.0%로 높습니다.',
        '메모리 사용률을 확인할 수 없습니다.',
        '로드 평균 0.12, 0.20, 0.18입니다.',
        '가동 시간 1시간 0분입니다.',
        '서비스 상태 ai-gateway=active, telegram-bot=active.',
        'Docker 컨테이너 실행 0개, 중지 0개입니다.',
        '자원 사용률이 높아 즉시 점검이 필요합니다.',
    ]


def test_format_agent_brain_summary_returns_warning_when_service_is_down():
    summary = SimpleNamespace(
        gateway='ok',
        disk_percent=50.0,
        memory_percent=40.0,
        load_average=[0.10, 0.20, 0.30],
        uptime_seconds=7200.0,
        service_states={'ai-gateway': 'failed', 'telegram-bot': 'active'},
        docker_summary={'running': 2, 'stopped': 0},
    )

    presentation = format_agent_brain_summary(summary)

    assert presentation['overall_status'] == 'warning'
    assert presentation['message_lines'][5] == '서비스 상태 ai-gateway=failed, telegram-bot=active.'
    assert presentation['message_lines'][-1] == '서비스 상태 경고가 감지되어 즉시 점검이 필요합니다.'
