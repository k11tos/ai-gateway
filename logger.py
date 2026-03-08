import logging
import os

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "gateway.log")

os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("ai_gateway")
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(LOG_FILE)
formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

file_handler.setFormatter(formatter)

logger.addHandler(file_handler)
