import logging

from . import custom_logging, config


def main():
    custom_logging.set_up_logging()

    config_data = config.read_config()
    custom_logging.set_logging_config(config_data)

    logging.info("Hello, World!")
