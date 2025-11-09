import json
import logging
import socket
import time
import traceback
from datetime import datetime, timezone
from threading import Thread
from typing import Any, Deque, Dict

GARBAGE_COLLECT_AGE = 60*60 # Maximum age for output data until it's discarded in seconds

class AutoRXListener():
    def __init__(self, autorx_host: str, autorx_port: int, out_queue: Deque[Dict[str, Any]]):

        self.autorx_host = autorx_host
        self.autorx_port = autorx_port
        self.out_queue = out_queue

        self._run_listener = False
        self._listener_thread = None
        self._socket = None

    def _garbage_collect_output(self):
        """Check if data in output is old and if it should be discarded"""

        if len(self.out_queue) == 0:
            return

        output_data_age = (self.out_queue[0]["time"] - datetime.now(timezone.utc)).total_seconds()
        if output_data_age >= GARBAGE_COLLECT_AGE:
            logging.info(f"Discarding sonde data due to it being more that {GARBAGE_COLLECT_AGE/60}min old")
            self.out_queue.clear()

    def _listen(self):
        """Listen for payload summaries from autorx"""

        # Configure socket
        self._socket = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        self._socket.settimeout(1)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except:
            pass
        
        try:
            # Bind socket
            self._socket.bind((self.autorx_host, self.autorx_port))

            # Start listening for packets
            logging.info(f"Started AutoRX listener on {self.autorx_host}:{self.autorx_port}")
            self._run_listener = True
            garbage_collect_counter = 0
            while self._run_listener:
                # Try to receive a packet
                try:
                    packet = json.loads(self._socket.recvfrom(1024)[0])
                    if packet["type"] == "PAYLOAD_SUMMARY":
                        logging.debug(f"Got packet from sonde {packet['callsign']}")

                        # Add time to packet
                        packet["time"] = datetime.now(timezone.utc)

                        self.out_queue.append(packet)
                except socket.timeout:
                    pass

                # Garbage collect output every 10th loop (every 10 seconds)
                garbage_collect_counter += 1
                if garbage_collect_counter == 10:
                    self._garbage_collect_output()
                    garbage_collect_counter = 0
        except (KeyboardInterrupt, Exception) as e:
            logging.error("Caught exception while running AutoRX listener: "+str(e))
            logging.info(traceback.format_exc())
            self.close()

    def start(self):
        """Start the AutoRX listener thread"""

        if self._listener_thread is None:
            self._listener_thread = Thread(target=self._listen)
            self._listener_thread.start()

    def close(self):
        """Stop the AutoRX listener thread"""

        if self._listener_thread is not None:
            self._run_listener = False

            # This won't work if this thread is calling the function
            try:
                self._listener_thread.join(timeout=3)
            except RuntimeError:
                pass

            self._listener_thread = None