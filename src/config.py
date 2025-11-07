import logging
import os
from typing import Any, Dict, Set

import tomllib

_config_data: dict = {} # internal variable to store read config data

def _extract_toml_keys(input_dict: Dict[str, Dict[str, Any]]) -> Dict[str, Set[str]]:
    """Return all keys available keys in a TOML file."""

    keys = {}
    for k, v in input_dict.items():
        keys[k] = set(v.keys())

    return keys

def read_config() -> Dict[str, Any]:
    """Read and parse the config file. Will only read file once, and after that always return the previously read config values."""

    global _config_data

    # Only read once for each program run
    if _config_data == {}:
        # Check if config file exists
        if not os.path.exists("config.toml"):
            logging.error("Couldn't find config file 'config.toml'!")

        # Read config file
        logging.debug("Reading config file")
        with open("config.toml", "rb") as f:
            _config_data = tomllib.load(f)

        if not os.path.exists("config.example.toml"): # If example config file doesn't exist, warn user and skip check.
            logging.warning("Couldn't find example config file! Program will still continue, but the check for invalid keys in the config file will be skipped.")
        else:
            # Read example config file to get correct keys
            with open("config.example.toml", "rb") as f:
                config_example_data = tomllib.load(f)

            if _extract_toml_keys(_config_data) != _extract_toml_keys(config_example_data):
                logging.error("Config file contains unexpected keys. Either the config file or the example config file contain invalid keys.")
                exit(1)

    return _config_data