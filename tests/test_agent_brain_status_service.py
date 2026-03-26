from services.agent_brain_status_service import collect_local_server_status
from services.agent_brain_status_service import _disk_percent_for_path
from services.agent_brain_status_service import _docker_summary
from services.agent_brain_status_service import _memory_percent


def test_collect_local_server_status_returns_expected_shape(monkeypatch):
    monkeypatch.setattr(
        'services.agent_brain_status_service._disk_percent_for_path',
        lambda path: 71.2,
    )
    monkeypatch.setattr(
        'services.agent_brain_status_service._memory_percent',
        lambda: 53.4,
    )
    monkeypatch.setattr(
        'services.agent_brain_status_service._load_average',
        lambda: [0.12, 0.20, 0.18],
    )
    monkeypatch.setattr(
        'services.agent_brain_status_service._uptime_seconds',
        lambda: 3723.0,
    )
    monkeypatch.setattr(
        'services.agent_brain_status_service._selected_service_states',
        lambda: {'ai-gateway': 'active', 'telegram-bot': 'active'},
    )
    monkeypatch.setattr(
        'services.agent_brain_status_service._docker_summary',
        lambda: {'running': 2, 'stopped': 1},
    )

    assert collect_local_server_status() == {
        'gateway': 'ok',
        'disk_percent': 71.2,
        'memory_percent': 53.4,
        'load_average': [0.12, 0.20, 0.18],
        'uptime_seconds': 3723.0,
        'service_states': {'ai-gateway': 'active', 'telegram-bot': 'active'},
        'docker_summary': {'running': 2, 'stopped': 1},
    }


def test_collect_local_server_status_degrades_per_metric(monkeypatch):
    monkeypatch.setattr(
        'services.agent_brain_status_service._disk_percent_for_path',
        lambda path: (_ for _ in ()).throw(OSError('disk unavailable')),
    )
    monkeypatch.setattr(
        'services.agent_brain_status_service._memory_percent',
        lambda: 40.0,
    )
    monkeypatch.setattr(
        'services.agent_brain_status_service._load_average',
        lambda: (_ for _ in ()).throw(AttributeError('unsupported')),
    )
    monkeypatch.setattr(
        'services.agent_brain_status_service._uptime_seconds',
        lambda: (_ for _ in ()).throw(OSError('uptime unavailable')),
    )
    monkeypatch.setattr(
        'services.agent_brain_status_service._selected_service_states',
        lambda: {'ai-gateway': None, 'telegram-bot': 'active'},
    )
    monkeypatch.setattr(
        'services.agent_brain_status_service._docker_summary',
        lambda: None,
    )

    assert collect_local_server_status() == {
        'gateway': 'ok',
        'disk_percent': None,
        'memory_percent': 40.0,
        'load_average': None,
        'uptime_seconds': None,
        'service_states': {'ai-gateway': None, 'telegram-bot': 'active'},
        'docker_summary': None,
    }


def test_disk_percent_is_calculated_from_disk_usage():
    percent = _disk_percent_for_path(
        '/',
        disk_usage_fn=lambda _path: (100, 35, 65),
    )

    assert percent == 35.0


def test_memory_percent_uses_memtotal_and_memavailable():
    percent = _memory_percent(
        meminfo_reader=lambda: {
            'MemTotal': 1000,
            'MemAvailable': 250,
        }
    )

    assert percent == 75.0


def test_docker_summary_returns_none_when_docker_is_unavailable(monkeypatch):
    monkeypatch.setattr('services.agent_brain_status_service.shutil.which', lambda _name: None)

    assert _docker_summary() is None
