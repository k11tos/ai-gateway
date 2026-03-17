import os
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


def collect_local_server_status() -> dict[str, str | float | list[float] | None]:
    disk_percent = None
    memory_percent = None
    load_average = None

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

    return {
        'gateway': 'ok',
        'disk_percent': disk_percent,
        'memory_percent': memory_percent,
        'load_average': load_average,
    }
