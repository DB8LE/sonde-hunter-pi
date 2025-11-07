import logging
import platform
import sys
from typing import Any, Dict


class CustomFormatter(logging.Formatter):
    """
    A custom logging formatter with the option to use ANSI escape codes for coloring the output.
    """

    def __init__(self, use_color=True):
        self.use_color = use_color

        # ANSI escape codes for coloring
        self.RESET  = "\x1b[0m"
        self.RED    = "\x1b[31m"
        self.YELLOW = "\x1b[33m"

        self.FORMAT = "[%(asctime)s] (%(levelchar)s) %(message)s"

        self.LEVEL_MAP = {
            logging.ERROR:   ("E", self.RED),
            logging.WARNING: ("W", self.YELLOW),
            logging.INFO:    ("I", ""),  # no color
            logging.DEBUG:   ("D", ""),  # no color
        }

    def format(self, record):
        levelno = record.levelno
        char, color = self.LEVEL_MAP.get(levelno, ("?", ""))

        # Inject new attributes into the record
        record.levelchar = char
        fmt = self.FORMAT
        if self.use_color:
            fmt = color + self.FORMAT + self.RESET
        formatter = logging.Formatter(fmt, "%H:%M:%S")

        return formatter.format(record)

def handle_uncaught(exc_type, exc_value, exc_tb):
    """A function to show uncaught exceptions by sending them to logging"""

    logging.log(logging.ERROR, "Unhandled exception: %s", exc_value)
    logging.log(logging.DEBUG, "Full traceback:", exc_info=(exc_type, exc_value, exc_tb))
    sys.exit(1)

def set_logging_config(config: Dict[str, Dict[str, Any]]):
    """
    Set additional logging settings according to the config file.
    App name used for file name has to be specified in set_up_logging
    """

    # Get root logger
    root_logger = logging.getLogger()

    # Set stdout logging level
    stdout_level = logging.DEBUG if config["logging"]["stdout_debug"] else logging.INFO
    root_logger.handlers[0].setLevel(stdout_level)

    # If enabled, set up logging to file
    if config["logging"]["log_to_file"]:
        file_handler = logging.FileHandler("sonde-hunter-pi.log", mode="a", encoding="utf-8")
        file_handler.setFormatter(CustomFormatter(use_color=False))

        # Set debug level if enabled
        file_log_level = logging.DEBUG if config["logging"]["file_debug"] else logging.INFO
        file_handler.setLevel(file_log_level)

        root_logger.addHandler(file_handler)

    # Set journal logger to debug if enabled
    if (len(root_logger.handlers) == 2) and config["logging"]["journal_debug"]:
        journal_level = logging.DEBUG if config["logging"]["journal_debug"] else logging.INFO
        root_logger.handlers[1].setLevel(journal_level) # Janky but the journal handler should always be second

def set_up_logging():
    """Set up the loggging system"""

    # Set exceptions to be handeled by custom function
    sys.excepthook = handle_uncaught

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Logging handler to log to stdout
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(CustomFormatter())
    stdout_handler.setLevel(logging.INFO)
    root_logger.addHandler(stdout_handler)

    # On linux, try to set up logging to the systemd journal
    if platform.system() == "Linux":
        try:
            from systemd.journal import JournalHandler

            journal_handler = JournalHandler(SYSLOG_IDENTIFIER="sonde-hunter-pi")
            journal_handler.setLevel(logging.INFO)
            root_logger.addHandler(journal_handler)
        except ImportError:
            logging.info("Failed to import python systemd module. Logging to the journal will be disabled. To install journald support, run poetry install with --with journald")