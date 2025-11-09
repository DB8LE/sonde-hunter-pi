import geopy.distance
import logging
import os
import queue
import tkinter as tk
from datetime import datetime, timezone
from geographiclib.geodesic import Geodesic
from luma.core.device import device
from luma.core.interface.serial import spi, noop
from luma.core.render import canvas
from luma.lcd.device import ili9341
from PIL import Image, ImageDraw, ImageFont, ImageTk
from threading import Thread
from typing import Any, Dict, Literal, Optional, Tuple


def calculate_bearing(point_a: Tuple[float, float], point_b: Tuple[float, float]) -> float:
    result = Geodesic.WGS84.Inverse(point_a[0], point_a[1], point_b[0], point_b[1],)
    bearing = result["azi1"] % 360

    return bearing

def latlon_to_human(latlon: float, which: Literal["lat", "lon"], decimals: int) -> str:
    """Converts either a latitude or longitude to a human readable string with a specified amount of decimal places"""

    abc = 1
    latlon_string = "{:.{}f}".format(round(abs(latlon), decimals), decimals)

    if which == "lat":
        latlon_string += ("S" if latlon < 0 else "N")
    elif which == "lon":
        latlon_string += ("W" if latlon < 0 else "E")

    return latlon_string

class SoftwareViewerDevice(device):
    def __init__(self, width: int, height: int, rotate: int = 0, mode: str = "RGB", **kwargs):
        super(SoftwareViewerDevice, self).__init__(serial_interface=noop())
        self.capabilities(width, height, rotate, mode)
        self.image_queue = queue.Queue()

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
    
    def run_tkinter(self):
        self.tk_root = tk.Tk()
        self.tk_root.title("Sonde Hunter Pi View")
        self.tk_root.geometry(f"{self.width}x{self.height}")
        self.tk_canvas = tk.Canvas(self.tk_root, width=self.width, height=self.height)
        self.tk_canvas.pack()
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
            driver: str,
            spi_port: int,
            spi_device: int,
            gpio_dc: int,
            gpio_rst: int,
            flip_display: bool
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
            self.display = SoftwareViewerDevice(width=width, height=height, rotate=rotate)

            # Run tkinter window in seperate thread
            Thread(target=self.display.run_tkinter, daemon=True).start()
        elif driver == "ILI9341":
            serial = spi(port=spi_port, device=spi_device, gpio_DC=gpio_dc, gpio_RST=gpio_rst)
            self.display = ili9341(serial, width=width, height=height, rotate=rotate)
            self.display.backlight(False) # False means on for some reason??
        else:
            logging.error("Unsupported display driver: "+driver)
            exit(1)
        
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

    def update(self, gpsd_data: Dict[str, Any], autorx_data: Optional[Dict[str, Any]], gps_reliable: bool):
        """Update screen with newest data from AutoRX and GPSD"""

        # Bottom GPS status text
        gps_status_text = f"{gpsd_data['satellites']} SVS   {gpsd_data['fix']} FIX"

        # Draw to screen
        with canvas(self.display) as draw:
            if autorx_data is None:
                self._display_idle_screen(draw)
            else:
                self._display_tracking_screen(draw, gpsd_data, autorx_data, gps_reliable)

            # Draw bottom status text
            draw.text((5, 215), gps_status_text, font=self.font, fill=self.TEXT_COLOR)
        
            # Draw time in bottom right corner
            time_text = datetime.now().strftime("%H:%M")
            draw.text((265, 215), time_text, font=self.font, fill=self.TEXT_COLOR)
