import logging

from . import custom_logging


def main():
    custom_logging.set_up_logging()

    logging.info("Hello, World!")
