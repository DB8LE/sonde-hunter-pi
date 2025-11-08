import json
import logging
import socket
import traceback
from collections import deque
from threading import Thread


class AutoRXListener():
    def __init__(self, autorx_host: str, autorx_port: int, out_queue: deque):

        self.autorx_host = autorx_host
        self.autorx_port = autorx_port
        self.out_queue = out_queue

        self._run_listener = False
        self._listener_thread = None
        self._socket = None

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
            while self._run_listener:
                # Try to receive a packet
                try:
                    packet = json.loads(self._socket.recvfrom(1024)[0])
                    if packet["type"] == "PAYLOAD_SUMMARY":
                        logging.debug(f"Got packet from sonde {packet['callsign']}")

                        self.out_queue.append(packet)
                except socket.timeout:
                    pass
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