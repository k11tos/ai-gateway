from services.agent_brain_status_service import collect_local_server_status
from services.agent_brain_status_service import _disk_percent_for_path
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

    assert collect_local_server_status() == {
        'gateway': 'ok',
        'disk_percent': 71.2,
        'memory_percent': 53.4,
        'load_average': [0.12, 0.20, 0.18],
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

    assert collect_local_server_status() == {
        'gateway': 'ok',
        'disk_percent': None,
        'memory_percent': 40.0,
        'load_average': None,
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
