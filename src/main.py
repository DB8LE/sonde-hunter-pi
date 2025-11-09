import logging
import signal
import time
import traceback
from collections import deque
from typing import Any, Deque, Dict

from . import autorx, config, custom_logging, display, gpsd


def main():
    # Set up logging
    custom_logging.set_up_logging()

    # Read config
    config_data = config.read_config()
    custom_logging.set_logging_config(config_data)

    # Start GPSD listener
    gpsd_data: Deque[Dict[str, Any]] = deque(maxlen=1)
    gpsd_listener = gpsd.GPSDListener(config_data["gpsd"]["host"], config_data["gpsd"]["port"], gpsd_data)
    gpsd_listener.start()

    # Start AutoRX listener
    autorx_data: Deque[Dict[str, Any]] = deque(maxlen=1)
    autorx_listener = autorx.AutoRXListener(config_data["autorx"]["host"], config_data["autorx"]["port"], autorx_data)
    autorx_listener.start()

    # Start display controller
    display_controller = display.DisplayController(
        config_data["display"]["driver"],
        config_data["display"]["spi_port"],
        config_data["display"]["spi_device"],
        config_data["display"]["gpio_dc"],
        config_data["display"]["gpio_rst"],
        config_data["display"]["flip_display"]
    )

    # Define close function
    def close(signum = None, frame = None):
        autorx_listener.close()
        gpsd_listener.close()
        display_controller.close()

    # Handle SIGINT and SIGTERM by closing
    signal.signal(signal.SIGINT, close)
    signal.signal(signal.SIGTERM, close)

    try:
        # Wait until GPSD listener outputs data (should happen almost immediatly, just to be safe)
        logging.debug("Waiting for first GPSD data")
        start_wait = time.time()
        while len(gpsd_data) == 0:
            if (time.time() - start_wait) >= 10:
                logging.error("No data received from GPSD within 10 seconds")
                exit(1)
            
            time.sleep(0.5)

        # Start main loop
        logging.info("Entering main loop")
        gps_fixes = deque(maxlen=10)
        while True:
            # Read latest GPSD and AutoRX data
            latest_gpsd_data = gpsd_data[0]
            latest_autorx_data = None if len(autorx_data) == 0 else autorx_data[0]

            logging.debug("AutoRX: "+str(latest_autorx_data))
            logging.debug("GPSD: "+str(latest_gpsd_data))

            # Check if GPS fix is unreliable
            gps_fixes.append(latest_gpsd_data["fix"])
            gps_reliable = "NO" not in gps_fixes
            if not gps_reliable:
                logging.debug("GPS is not reliable")

            # Update display
            display_controller.update(latest_gpsd_data, latest_autorx_data, gps_reliable)

            time.sleep(1)
    except Exception as e:
        logging.error(f"Caught exception: {e}")
        logging.debug(traceback.format_exc())
    except KeyboardInterrupt:
        logging.info("Caught KeyboardInterrupt, shutting down")
    finally:
        close()
