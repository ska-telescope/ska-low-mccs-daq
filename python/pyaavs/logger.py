from logging.handlers import TimedRotatingFileHandler
import logging
import sys

# Set up default logging (and remove existing loggers)
root_logger = logging.getLogger()
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(threadName)s - %(message)s")
root_logger.setLevel(logging.INFO)
root_logger.handlers = []

# Set file handler
handler = TimedRotatingFileHandler("/opt/aavs/log/aavs.log", when="h", interval=1, backupCount=180, utc=True)
handler.setFormatter(formatter)
handler.setLevel(logging.INFO)
root_logger.addHandler(handler)

# Set console handler
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(formatter)
handler.setLevel(logging.INFO)
root_logger.addHandler(handler)


def set_console_log_level(log_level="INFO"):
    h = logging.StreamHandler(sys.stdout)
    if log_level == "INFO":
        h.setLevel(logging.INFO)
    elif log_level == "DEBUG":
        h.setLevel(logging.DEBUG)
