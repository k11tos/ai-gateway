from types import SimpleNamespace

from services.agent_brain_change_formatter import format_agent_brain_changes


def _change_set(**overrides):
    defaults = {
        'has_previous_snapshot': True,
        'restart_detected': False,
        'previous_uptime_seconds': 3600.0,
        'current_uptime_seconds': 3660.0,
        'metric_deltas': [],
        'service_state_changes': [],
        'docker_summary_change': None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_metric_memory_decrease_is_non_notable():
    changes = format_agent_brain_changes(
        _change_set(
            metric_deltas=[
                SimpleNamespace(name='memory_percent', previous=48.9, current=43.4),
            ]
        )
    )

    assert changes['changes'] == [
        {
            'kind': 'metric_delta',
            'field': 'memory_percent',
            'previous': 48.9,
            'current': 43.4,
            'notable': False,
        }
    ]
    assert changes['has_notable_changes'] is False


def test_small_memory_increase_is_non_notable():
    changes = format_agent_brain_changes(
        _change_set(
            metric_deltas=[
                SimpleNamespace(name='memory_percent', previous=43.4, current=43.5),
            ]
        )
    )

    assert changes['changes'][0]['notable'] is False
    assert changes['has_notable_changes'] is False


def test_meaningful_memory_increase_is_notable():
    changes = format_agent_brain_changes(
        _change_set(
            metric_deltas=[
                SimpleNamespace(name='memory_percent', previous=43.4, current=48.4),
            ]
        )
    )

    assert changes['changes'][0]['notable'] is True
    assert changes['has_notable_changes'] is True


def test_memory_warning_threshold_crossing_is_notable():
    changes = format_agent_brain_changes(
        _change_set(
            metric_deltas=[
                SimpleNamespace(name='memory_percent', previous=89.9, current=90.1),
            ]
        )
    )

    assert changes['changes'][0]['notable'] is True
    assert changes['has_notable_changes'] is True


def test_disk_decrease_is_non_notable():
    changes = format_agent_brain_changes(
        _change_set(
            metric_deltas=[
                SimpleNamespace(name='disk_percent', previous=61.0, current=58.0),
            ]
        )
    )

    assert changes['changes'][0]['notable'] is False
    assert changes['has_notable_changes'] is False


def test_small_disk_increase_is_non_notable():
    changes = format_agent_brain_changes(
        _change_set(
            metric_deltas=[
                SimpleNamespace(name='disk_percent', previous=61.0, current=61.2),
            ]
        )
    )

    assert changes['changes'][0]['notable'] is False
    assert changes['has_notable_changes'] is False


def test_meaningful_disk_increase_is_notable():
    changes = format_agent_brain_changes(
        _change_set(
            metric_deltas=[
                SimpleNamespace(name='disk_percent', previous=61.0, current=66.0),
            ]
        )
    )

    assert changes['changes'][0]['notable'] is True
    assert changes['has_notable_changes'] is True


def test_load_average_decrease_is_non_notable():
    changes = format_agent_brain_changes(
        _change_set(
            metric_deltas=[
                SimpleNamespace(name='load_average', previous=0.40, current=0.20),
            ]
        )
    )

    assert changes['changes'][0]['notable'] is False
    assert changes['has_notable_changes'] is False


def test_small_load_average_increase_is_non_notable():
    changes = format_agent_brain_changes(
        _change_set(
            metric_deltas=[
                SimpleNamespace(name='load_average', previous=0.32, current=0.34),
            ]
        )
    )

    assert changes['changes'][0]['notable'] is False
    assert changes['has_notable_changes'] is False


def test_meaningful_load_average_increase_is_notable():
    changes = format_agent_brain_changes(
        _change_set(
            metric_deltas=[
                SimpleNamespace(name='load_average', previous=0.32, current=0.83),
            ]
        )
    )

    assert changes['changes'][0]['notable'] is True
    assert changes['has_notable_changes'] is True


def test_restart_detected_remains_notable():
    changes = format_agent_brain_changes(
        _change_set(
            restart_detected=True,
            previous_uptime_seconds=7200.0,
            current_uptime_seconds=120.0,
        )
    )

    assert changes['changes'] == [
        {
            'kind': 'restart_detected',
            'field': 'uptime_seconds',
            'previous': 7200.0,
            'current': 120.0,
            'notable': True,
        }
    ]
    assert changes['has_notable_changes'] is True


def test_service_regression_remains_notable_and_recovery_is_non_notable():
    changes = format_agent_brain_changes(
        _change_set(
            service_state_changes=[
                SimpleNamespace(service_name='ai-gateway', previous_state='active', current_state='failed'),
                SimpleNamespace(service_name='telegram-bot', previous_state='failed', current_state='active'),
            ]
        )
    )

    assert changes['changes'] == [
        {
            'kind': 'service_state_change',
            'field': 'service_states.ai-gateway',
            'previous': 'active',
            'current': 'failed',
            'notable': True,
        },
        {
            'kind': 'service_state_change',
            'field': 'service_states.telegram-bot',
            'previous': 'failed',
            'current': 'active',
            'notable': False,
        },
    ]
    assert changes['has_notable_changes'] is True


def test_service_recovery_only_is_non_notable():
    changes = format_agent_brain_changes(
        _change_set(
            service_state_changes=[
                SimpleNamespace(service_name='ai-gateway', previous_state='failed', current_state='active'),
            ]
        )
    )

    assert changes['changes'][0]['notable'] is False
    assert changes['has_notable_changes'] is False


def test_docker_worsening_remains_notable():
    changes = format_agent_brain_changes(
        _change_set(
            docker_summary_change=SimpleNamespace(
                previous_running=2,
                current_running=1,
                previous_stopped=1,
                current_stopped=2,
            )
        )
    )

    assert changes['changes'][0]['notable'] is True
    assert changes['has_notable_changes'] is True
