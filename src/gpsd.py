import json
import logging
import socket
import traceback
from collections import deque
from threading import Thread
from typing import Any, Deque, Dict

class GPSDListener:
    def __init__(self, gpsd_host: str, gpsd_port: int, out_queue: Deque[Dict[str, Any]]) -> None:
        self.gpsd_host = gpsd_host
        self.gpsd_port = gpsd_port
        self.out_queue = out_queue

        self._run_listener = False
        self._listener_thread = None
        self._socket = None

    def _receive_response(self) -> Dict[str, Any]:
        """Receive data from the GPSD socket"""

        assert self._socket is not None

        # Receive data until newline is detected
        buffer = ""
        while "\n" not in buffer:
            chunk = self._socket.recv(1).decode("utf-8")
            buffer += chunk
        buffer = buffer.strip()

        # Decode JSON
        json_data = json.loads(buffer)

        return json_data

    def _process_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Process a singular GPSD response and return relevat data out of that response"""

        out = {}

        try:
            if response["class"] == "TPV":
                fix = response["mode"]

                if fix > 1:
                    out["latitude"] = response["lat"]
                    out["longitude"] = response["lon"]

                if fix <= 1:
                    out["fix"] = "NO"
                elif fix == 2:
                    out["fix"] = "2D"
                elif fix == 3:
                    out["fix"] = "3D"
                    out["altitude"] = response["alt"]
            elif response["class"] == "SKY":
                if "satellites" in response:
                    used = 0
                    for satellite in response["satellites"]:
                        if satellite["used"]:
                            used += 1

                    out["satellites"] = used
        except KeyError as e:
            logging.error("GPSD response missing field: "+str(e))

            return {}

        return out

    def _listen(self):
        """Listen for data from GPSD"""

        try:
            # Connect to GPSD
            self._socket = socket.create_connection((self.gpsd_host, self.gpsd_port))

            # Send command to GPSD to return JSON data
            self._socket.send(b'?WATCH={"enable": true, "json": true}\n')

            # Try to receive version info
            version = "?"
            try:
                response = self._receive_response()

                if response["class"] == "VERSION":
                    version = response["release"]
                else:
                    raise ValueError("First message from GPSD was not version info.")
            except Exception as e:
                logging.warning("Couldn't receive version header from GPSD: "+str(e))

            # Push dict with placeholders into output
            latest_output = {"latitude": 0.0, "longitude": 0.0, "altitude": 0.0, "satellites": 0, "fix": "NO"}
            self.out_queue.append(latest_output)

            # Start listening
            logging.info(f"Started GPSD (v{version}) listener on {self.gpsd_host}:{self.gpsd_port}")
            self._run_listener = True
            while self._run_listener:
                # Get data from GPSD and extract important fields
                response = self._receive_response()
                response_info = self._process_response(response)

                # Update latest output and output queue
                latest_output.update(response_info)
                self.out_queue.append(latest_output)
                    
        except (KeyboardInterrupt, Exception) as e:
            logging.error("Caught exception while running GPSD listener: "+str(e))
            logging.info(traceback.format_exc())
            self.close()

    def start(self):
        """Start GPSD listener thread"""

        if self._listener_thread is None:
            self._listener_thread = Thread(target=self._listen)
            self._listener_thread.start()

    def close(self):
        """Stop GPSD listener thread"""

        if self._listener_thread is not None:
            self._run_listener = False

            # This won't work if this thread is calling the function
            try:
                self._listener_thread.join(timeout=3)
            except RuntimeError:
                pass

            self._listener_thread = None
