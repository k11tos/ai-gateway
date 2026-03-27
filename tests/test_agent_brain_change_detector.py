from dataclasses import dataclass

from services.agent_brain_change_detector import detect_agent_brain_changes


@dataclass
class Snapshot:
    disk_percent: float | None
    memory_percent: float | None
    load_average: list[float] | None
    uptime_seconds: float | None
    service_states: dict[str, str | None] | None
    docker_summary: dict[str, int] | None


def _snapshot(**overrides) -> Snapshot:
    defaults = {
        'disk_percent': 50.0,
        'memory_percent': 55.0,
        'load_average': [0.6, 0.5, 0.4],
        'uptime_seconds': 3600.0,
        'service_states': {'ai-gateway': 'active', 'telegram-bot': 'active'},
        'docker_summary': {'running': 2, 'stopped': 1},
    }
    defaults.update(overrides)
    return Snapshot(**defaults)


def test_detect_agent_brain_changes_without_previous_snapshot():
    first = detect_agent_brain_changes(None, _snapshot())
    second = detect_agent_brain_changes(None, _snapshot())

    assert first.has_previous_snapshot is False
    assert first.restart_detected is False
    assert first.uptime_drop_seconds is None
    assert first.previous_uptime_seconds is None
    assert first.current_uptime_seconds is None
    assert first.metric_deltas == []
    assert first.service_state_changes == []
    assert first.docker_summary_change is None

    assert first is not second
    assert first.metric_deltas is not second.metric_deltas
    assert first.service_state_changes is not second.service_state_changes


def test_detect_agent_brain_changes_detects_restart_from_uptime_drop():
    previous = _snapshot(uptime_seconds=7200.0)
    current = _snapshot(uptime_seconds=120.0)

    changes = detect_agent_brain_changes(previous, current)

    assert changes.has_previous_snapshot is True
    assert changes.restart_detected is True
    assert changes.uptime_drop_seconds == 7080.0
    assert changes.previous_uptime_seconds == 7200.0
    assert changes.current_uptime_seconds == 120.0


def test_detect_agent_brain_changes_detects_service_state_change():
    previous = _snapshot(service_states={'ai-gateway': 'active', 'telegram-bot': 'active'})
    current = _snapshot(service_states={'ai-gateway': 'failed', 'telegram-bot': 'active'})

    changes = detect_agent_brain_changes(previous, current)

    assert len(changes.service_state_changes) == 1
    service_change = changes.service_state_changes[0]
    assert service_change.service_name == 'ai-gateway'
    assert service_change.previous_state == 'active'
    assert service_change.current_state == 'failed'


def test_detect_agent_brain_changes_detects_docker_count_change():
    previous = _snapshot(docker_summary={'running': 2, 'stopped': 1})
    current = _snapshot(docker_summary={'running': 1, 'stopped': 2})

    changes = detect_agent_brain_changes(previous, current)

    assert changes.docker_summary_change is not None
    assert changes.docker_summary_change.previous_running == 2
    assert changes.docker_summary_change.current_running == 1
    assert changes.docker_summary_change.previous_stopped == 1
    assert changes.docker_summary_change.current_stopped == 2


def test_detect_agent_brain_changes_applies_disk_memory_thresholds():
    previous = _snapshot(disk_percent=40.0, memory_percent=50.0)
    current = _snapshot(disk_percent=46.0, memory_percent=54.9)

    changes = detect_agent_brain_changes(previous, current)

    delta_names = [delta.name for delta in changes.metric_deltas]
    assert 'disk_percent' in delta_names
    assert 'memory_percent' not in delta_names
