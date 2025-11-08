import logging
import time
import traceback
from collections import deque

from . import autorx, config, custom_logging, gpsd


def main():
    custom_logging.set_up_logging()

    config_data = config.read_config()
    custom_logging.set_logging_config(config_data)

    autorx_data = deque(maxlen=1)
    autorx_listener = autorx.AutoRXListener(config_data["autorx"]["host"], config_data["autorx"]["port"], autorx_data)
    autorx_listener.start()

    gpsd_data = deque(maxlen=1)
    gpsd_listener = gpsd.GPSDListener(config_data["gpsd"]["host"], config_data["gpsd"]["port"], gpsd_data)
    gpsd_listener.start()

    try:
        while True:
            time.sleep(1)

            if len(autorx_data) != 0:
                logging.debug("AutoRX: "+str(autorx_data[0]))

            if len(gpsd_data) != 0:
                logging.debug("GPSD: "+str(gpsd_data[0]))
    except Exception as e:
        logging.error(f"Caught exception: {e}")
        logging.debug(traceback.format_exc())
    except KeyboardInterrupt:
        logging.info("Caught KeyboardInterrupt, shutting down")
    finally:
        autorx_listener.close()
        gpsd_listener.close()
