import geopy.distance
import logging
import os
import qrcode
import queue
import time
import tkinter as tk
from collections import deque
from datetime import datetime, timezone
from geographiclib.geodesic import Geodesic
from luma.core.device import device
from luma.core.interface.serial import spi, noop
from luma.core.render import canvas
from luma.lcd.device import ili9341
from PIL import Image, ImageDraw, ImageFont, ImageTk
from threading import Thread
from typing import Any, Deque, Dict, Literal, Optional, Tuple


def calculate_bearing(point_a: Tuple[float, float], point_b: Tuple[float, float]) -> float:
    result = Geodesic.WGS84.Inverse(point_a[0], point_a[1], point_b[0], point_b[1],)
    bearing = result["azi1"] % 360

    return bearing

def latlon_to_human(latlon: float, which: Literal["lat", "lon"], decimals: int) -> str:
    """Converts either a latitude or longitude to a human readable string with a specified amount of decimal places"""

    latlon_string = "{:.{}f}".format(round(abs(latlon), decimals), decimals)

    if which == "lat":
        latlon_string += ("S" if latlon < 0 else "N")
    elif which == "lon":
        latlon_string += ("W" if latlon < 0 else "E")

    return latlon_string

class SoftwareViewerDevice(device):
    def __init__(self, width: int, height: int, rotate: int = 0, mode: str = "RGB", touch_data: Optional[Deque] = None):
        super(SoftwareViewerDevice, self).__init__(serial_interface=noop())
        self.capabilities(width, height, rotate, mode)

        self.image_queue = queue.Queue()
        self.touch_queue = touch_data

    def _image_update_loop(self):
        try:
            tk_image = self.image_queue.get_nowait()
        except queue.Empty:
            pass
        else:
            # Keep a persistent reference
            self._tk_image_ref = tk_image

            if not hasattr(self, "_image_item"):
                # Create the canvas if its the first image
                self._image_item = self.tk_canvas.create_image(0, 0, anchor=tk.NW, image=tk_image)
            else:
                # Update the canvas
                self.tk_canvas.itemconfig(self._image_item, image=tk_image)

        self.tk_root.after(100, self._image_update_loop)

    def _mouse_click_callback(self, event: tk.Event):
        """Handle mouse clicks on the canvas"""

        assert self.touch_queue is not None

        # If screen is not flipped, touch coordinated need to be inverted to match usual driver output
        if self.rotate == 0:
            x = self.width - event.x
            y = self.height - event.y
        else:
            x = event.x
            y = event.y

        self.touch_queue.append((x, y))
    
    def run_tkinter(self):
        """Run tkinter and display images onto canvas"""

        # Initialize tkinter
        self.tk_root = tk.Tk()
        self.tk_root.title("Sonde Hunter Pi View")
        self.tk_root.geometry(f"{self.width}x{self.height}")
        
        # Add canvas for the display image
        self.tk_canvas = tk.Canvas(self.tk_root, width=self.width, height=self.height)
        self.tk_canvas.pack()

        # Bind mouse clicks on canvas to trigger mouse click callback (if touch queue was provided)
        if self.touch_queue is not None:
            self.tk_canvas.bind("<Button-1>", self._mouse_click_callback)

        # Start image update loop and enter main loop
        self._image_update_loop()
        self.tk_root.mainloop()

    def display(self, image: Image.Image):
        """Display an image onto the Tkinter window"""

        tk_image = ImageTk.PhotoImage(image)
        self.image_queue.put_nowait(tk_image)
        logging.debug("Image added to viewer image queue")

class DisplayController():
    TEXT_COLOR = "white"

    def __init__(
            self,
            driver: Literal["software", "ILI9341"],
            spi_port: int,
            spi_device: int,
            gpio_dc: int,
            gpio_rst: int,
            flip_display: bool,
            touch_data: Optional[Deque[Tuple[int, int]]] = None
        ) -> None:
        
        # Load font
        font_path = os.path.join(os.getcwd(), "assets/fonts/Roboto-Regular.ttf")
        bold_font_path = os.path.join(os.getcwd(), "assets/fonts/Roboto-Bold.ttf")
        if not os.path.isfile(font_path):
            logging.error("Couldn't find font file. Make sure the program is being run in the correct directory.")
            exit(1)
        self.head_font = ImageFont.truetype(bold_font_path, 32)
        self.font = ImageFont.truetype(font_path, 20)

        # Initialize display
        width = 320
        height = 240
        rotate = 2 if flip_display else 0
        if driver == "software":
            # If normal touch is disabled, make a touch queue for the software viewer
            if touch_data is None:
                touch_data = deque(maxlen=1)

            self.display = SoftwareViewerDevice(width=width, height=height, rotate=rotate, touch_data=touch_data)

            # Run tkinter window in seperate thread
            Thread(target=self.display.run_tkinter, daemon=True).start()
        elif driver == "ILI9341":
            serial = spi(port=spi_port, device=spi_device, gpio_DC=gpio_dc, gpio_RST=gpio_rst)
            self.display = ili9341(serial, width=width, height=height, rotate=rotate)
            self.display.backlight(False) # False means on for some reason??
        else:
            logging.error("Unsupported display driver: "+driver)
            exit(1)

        # Set up touchscreen
        self.touch_data = touch_data
        self.touch_buttons = [
            # start_x, start_y, end_x, end_y, target func.
            (100, 30, 70, 5, self._show_geo_qr)
        ]
        self.block_touch = False

        # Latest sonde position (for QR code)
        self.last_sonde_position: Optional[Tuple[float, float, datetime]] = None
        
        # Sleep variable
        self.sleep_time = 0

        logging.info("Initialized display")

    def _display_idle_screen(self, draw: ImageDraw.ImageDraw):
        """Display idle screen"""

        draw.text((5, 5), "Not tracking\nany sondes\nright now!", font=self.head_font, fill=self.TEXT_COLOR)

    def _display_tracking_screen(
            self,
            draw: ImageDraw.ImageDraw,
            gpsd_data: Dict[str, Any],
            autorx_data: Dict[str, Any],
            relative_mode: bool
        ):
        """Display tracking screen"""

        # Calculate sonde distance and decide wether to display long distance screen
        sonde_distance = round(geopy.distance.geodesic(
            (gpsd_data["latitude"], gpsd_data["longitude"]),
            (autorx_data["latitude"], autorx_data["longitude"])
        ).meters)

        far = False
        if (sonde_distance > 9999) or (autorx_data["altitude"] > 9999):
            far = True

        # Draw data to screen
        sonde_data_shift = 0
        if (relative_mode) and (not far):
            # Display sonde data and sonde position relative to user gps
            sonde_data_shift = 37 # Shift sonde data 37px down to make room for relative data

            # Calculate bearing
            sonde_bearing = round(calculate_bearing(
                (gpsd_data["latitude"], gpsd_data["longitude"]),
                (autorx_data["latitude"], autorx_data["longitude"])
            ))

            # Calculate height difference (if 3D fix is available)
            height_diff = "-"
            height_diff_symbol = ""
            if gpsd_data["fix"] == "3D":
                height_diff = round(autorx_data["altitude"] - gpsd_data["altitude"])
                height_diff_symbol = "+" if height_diff >= 0 else ""

            relative_text = f"{sonde_bearing}° {sonde_distance}m h{height_diff_symbol}{height_diff}m"

            draw.text((5, 5), relative_text, font=self.head_font, fill=self.TEXT_COLOR)

        # Prepare sonde data
        latlon_decimals = 4 if far else 5
        sonde_latitude = latlon_to_human(autorx_data['latitude'], "lat", latlon_decimals)
        sonde_longitude = latlon_to_human(autorx_data['longitude'], "lon", latlon_decimals)
        sonde_altitude = round(autorx_data['altitude'])

        sonde_data_age = (datetime.now(timezone.utc) - autorx_data["time"]).total_seconds()
        if sonde_data_age > 999:
            sonde_data_age = "old     "
        else:
            sonde_data_age = str(round(sonde_data_age)) + "s ago"
    
        sonde_frequency = round(float(autorx_data["freq"][:-4]), 2)
        sonde_snr = autorx_data["snr"]

        if far:
            # Prepare distance and altitude in km
            sonde_distance_km = "{0:.1f}".format(round(sonde_distance/1000, 1))
            sonde_altitude_km = "{0:.1f}".format(round(sonde_altitude/1000, 1))

            # Prepare head and sonde data texts
            head_text = f"{sonde_latitude} {sonde_longitude}"
            sonde_data_text = f"height: {sonde_altitude_km}km dist: {sonde_distance_km}km\n"
            sonde_data_text += f"{sonde_data_age}   {sonde_frequency}MHz {sonde_snr}dB"

            # Draw head and sonde data to screen
            draw.text((5, 5), head_text, font=self.head_font, fill=self.TEXT_COLOR)
            draw.text((5, 42), sonde_data_text, font=self.font, fill=self.TEXT_COLOR)
        else:
            # Prepare sonde data text
            sonde_data_text = f"{sonde_latitude} {sonde_longitude} {sonde_altitude}m\n"
            sonde_data_text += f"{sonde_data_age}   {sonde_frequency}MHz {sonde_snr}dB"

            # Draw sonde data text to screen
            draw.text((5, 5+sonde_data_shift), sonde_data_text, font=self.font, fill=self.TEXT_COLOR)

    def _show_geo_qr(self, draw: ImageDraw.ImageDraw):
        """Display the sonde geolocation QR code"""

        # Check if theres any sonde data available
        if self.last_sonde_position is None:
            draw.text((5, 5), "No sonde data yet", font=self.head_font, fill=self.TEXT_COLOR)
            self.sleep_time = 3

            return

        logging.debug("Showing sonde geolocation QR code")

        # Generate the QR code
        geo_data = f"geo:{self.last_sonde_position[0]},{self.last_sonde_position[1]}"

        qr_code = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=7,
            border=4,
        )
        qr_code.add_data(geo_data)
        qr_code.make(fit=True)

        qr_image = qr_code.make_image(fill_color="black", back_color="white")
        qr_image = qr_image.convert("RGBA")

        # TODO: maybe also draw how old the data in the QR is?
        # Draw QR code onto canvas
        for x in range(qr_image.width):
            for y in range(qr_image.height):
                pixel = qr_image.getpixel((x, y))
                draw.point((x, y), fill=pixel)

        self.sleep_time = 5

    def _check_touch(self, touch_point: Tuple[int, int], draw: ImageDraw.ImageDraw) -> bool:
        """Trigger any buttons for a certain touch location. Returns true if button was triggered"""

        button_triggered = False
        touch_x, touch_y = touch_point
        for start_x, start_y, end_x, end_y, target in self.touch_buttons:
            if (touch_x <= start_x) and (touch_y <= start_y) and (touch_x >= end_x) and (touch_y >= end_y):
                button_triggered = True
                self.block_touch = True # Block touch so the user can't press buttons during any wait time
                target(draw)

        return button_triggered

    def update(self, gpsd_data: Dict[str, Any], autorx_data: Optional[Dict[str, Any]], gps_reliable: bool):
        """Update screen with newest data from AutoRX and GPSD"""

        # Check if update loop should sleep
        if self.sleep_time > 0:
            logging.debug(f"Update loop sleeping for {self.sleep_time} seconds")

            time.sleep(self.sleep_time)
            self.sleep_time = 0

            return # Return cause the data is probably outdated now

        # Update latest sonde position
        if autorx_data is not None:
            self.last_sonde_position = (
                round(autorx_data["latitude"], 5),
                round(autorx_data["longitude"], 5),
                autorx_data["time"]
            )

        # Bottom GPS status text
        gps_satellites = "?" if "satellites" not in gpsd_data else gpsd_data['satellites']
        gps_status_text = f"{gps_satellites} SVS   {gpsd_data['fix']} FIX"

        # Draw to screen
        with canvas(self.display) as draw:
            # Check for touch events
            if self.touch_data is not None:
                if self.block_touch:
                    self.touch_data.clear()
                    logging.debug("Discarded touch data due to touch being blocked")
                
                if len(self.touch_data) > 0:
                    touch_point = self.touch_data[0]
                    self.touch_data.clear()

                    logging.debug(f"Display controller got touch at {touch_point}")

                    button_triggered = self._check_touch(touch_point, draw)

                    if button_triggered: # If a button was triggered, skip this update cycle

                        return
                    
            # Ensure touch is not blocked
            self.block_touch = False

            # Display either idle or tracking screen
            if autorx_data is None:
                self._display_idle_screen(draw)
            else:
                self._display_tracking_screen(draw, gpsd_data, autorx_data, gps_reliable)

            # Draw bottom status text
            draw.text((5, 215), gps_status_text, font=self.font, fill=self.TEXT_COLOR)

            # Draw QR button
            draw.text((230, 215), "QR", font=self.font, fill="yellow")
        
            # Draw time in bottom right corner
            time_text = datetime.now().strftime("%H:%M")
            draw.text((265, 215), time_text, font=self.font, fill=self.TEXT_COLOR)
    
    def close(self):
        self.display.cleanup()
