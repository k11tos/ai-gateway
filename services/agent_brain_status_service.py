import os
import subprocess
import shutil
from typing import Callable


def _read_linux_meminfo() -> dict[str, int]:
    meminfo: dict[str, int] = {}

    with open('/proc/meminfo', encoding='utf-8') as meminfo_file:
        for line in meminfo_file:
            key, _, value_part = line.partition(':')
            if not _:
                continue

            value_text = value_part.strip().split()[0]
            meminfo[key] = int(value_text)

    return meminfo


def _disk_percent_for_path(
    path: str,
    *,
    disk_usage_fn: Callable[[str], tuple[int, int, int]] = shutil.disk_usage,
) -> float:
    usage = disk_usage_fn(path)

    total = getattr(usage, 'total', usage[0])
    used = getattr(usage, 'used', usage[1])

    if total <= 0:
        raise ValueError('disk total must be positive')

    return (used / total) * 100.0


def _memory_percent(
    *,
    meminfo_reader: Callable[[], dict[str, int]] = _read_linux_meminfo,
) -> float:
    meminfo = meminfo_reader()

    total = meminfo['MemTotal']
    available = meminfo['MemAvailable']

    if total <= 0:
        raise ValueError('memory total must be positive')

    return ((total - available) / total) * 100.0


def _load_average(
    *,
    loadavg_fn: Callable[[], tuple[float, float, float]] = os.getloadavg,
) -> list[float]:
    return list(loadavg_fn())


def _uptime_seconds() -> float:
    with open('/proc/uptime', encoding='utf-8') as uptime_file:
        uptime_text = uptime_file.read().strip().split()[0]

    return float(uptime_text)


def _service_state(service_name: str) -> str | None:
    if shutil.which('systemctl') is None:
        return None

    completed = subprocess.run(
        ['systemctl', 'is-active', service_name],
        check=False,
        capture_output=True,
        text=True,
        timeout=1,
    )

    state = completed.stdout.strip()
    if state:
        return state

    if completed.returncode == 0:
        return 'active'

    return None


def _selected_service_states() -> dict[str, str | None] | None:
    if shutil.which('systemctl') is None:
        return None

    service_states: dict[str, str | None] = {}
    for service_name in ('ai-gateway', 'telegram-bot'):
        try:
            service_states[service_name] = _service_state(service_name)
        except (OSError, subprocess.SubprocessError):
            service_states[service_name] = None

    return service_states


def _docker_summary() -> dict[str, int] | None:
    if shutil.which('docker') is None:
        return None

    completed = subprocess.run(
        ['docker', 'ps', '-a', '--format', '{{.State}}'],
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )
    if completed.returncode != 0:
        return None

    states = [line.strip().lower() for line in completed.stdout.splitlines() if line.strip()]
    running = sum(1 for state in states if state.startswith('running'))
    stopped = len(states) - running
    return {
        'running': running,
        'stopped': stopped,
    }


def collect_local_server_status() -> dict[str, str | float | list[float] | dict[str, str | None] | dict[str, int] | None]:
    disk_percent = None
    memory_percent = None
    load_average = None
    uptime_seconds = None
    service_states = None
    docker_summary = None

    try:
        disk_percent = _disk_percent_for_path('/')
    except (OSError, ValueError, KeyError, TypeError):
        pass

    try:
        memory_percent = _memory_percent()
    except (OSError, ValueError, KeyError, TypeError):
        pass

    try:
        load_average = _load_average()
    except (OSError, ValueError, AttributeError):
        pass

    try:
        uptime_seconds = _uptime_seconds()
    except (OSError, ValueError, IndexError):
        pass

    try:
        service_states = _selected_service_states()
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        pass

    try:
        docker_summary = _docker_summary()
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        pass

    return {
        'gateway': 'ok',
        'disk_percent': disk_percent,
        'memory_percent': memory_percent,
        'load_average': load_average,
        'uptime_seconds': uptime_seconds,
        'service_states': service_states,
        'docker_summary': docker_summary,
    }
