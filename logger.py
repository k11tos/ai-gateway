import logging
import os
import sys

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "gateway.log")

os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("ai_gateway")
logger.setLevel(logging.INFO)

formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

has_file_handler = any(
    isinstance(handler, logging.FileHandler)
    and os.path.abspath(getattr(handler, "baseFilename", "")) == os.path.abspath(LOG_FILE)
    for handler in logger.handlers
)
if not has_file_handler:
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

has_stdout_handler = any(
    isinstance(handler, logging.StreamHandler)
    and getattr(handler, "stream", None) is sys.stdout
    for handler in logger.handlers
)
if not has_stdout_handler:
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
