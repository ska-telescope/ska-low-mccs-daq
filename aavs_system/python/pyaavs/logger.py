from logging.handlers import TimedRotatingFileHandler
import logging
import sys
import os

# Set up default logging (and remove existing loggers)
root_logger = logging.getLogger()
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(threadName)s - %(message)s")
root_logger.setLevel(logging.INFO)
root_logger.handlers = []

# Set file handler

aavs_install_path = os.environ.get("AAVS_INSTALL", "/opt/aavs")
file_handler = TimedRotatingFileHandler(f"{aavs_install_path}/log/aavs.log", when="h", interval=1, backupCount=180, utc=True)
file_handler.setFormatter(formatter)
file_handler.setLevel(logging.INFO)
root_logger.addHandler(file_handler)

# Set console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
console_handler.setLevel(logging.INFO)
root_logger.addHandler(console_handler)


def set_console_log_level(log_level="INFO"):
    if log_level == "INFO":
        root_logger.setLevel(logging.INFO)
        console_handler.setLevel(logging.INFO)
    elif log_level == "DEBUG":
        root_logger.setLevel(logging.DEBUG)
        console_handler.setLevel(logging.DEBUG)
