import logging
import os
import queue
import tkinter as tk
from datetime import datetime
from luma.core.device import device
from luma.core.interface.serial import spi, noop
from luma.core.render import canvas
from luma.lcd.device import ili9341
from PIL import Image, ImageFont, ImageTk
from threading import Thread
from typing import Any, Dict, Deque, Optional


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

    def __init__(self,
                 driver: str,
                 spi_port: int,
                 spi_device: int,
                 gpio_dc: int,
                 gpio_rst: int,
                 flip_display: bool
        ) -> None:
        
        # Load font
        font_path = os.path.join(os.getcwd(), "assets/fonts/Roboto-Regular.ttf")
        if not os.path.isfile(font_path):
            logging.error("Couldn't find font file. Make sure the program is being run in the correct directory.")
            exit(1)
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

        # Demo counter
        self.counter = 0

    def update(self, gpsd_data: Dict[str, Any], autorx_data: Optional[Dict[str, Any]]):
        """Update screen with newest data from AutoRX and GPSD"""

        # Increment demo counter
        self.counter += 1

        # Bottom GPS status text
        gps_status_text = f"{gpsd_data['satellites']} SVS   {gpsd_data['fix']} FIX"

        # Draw to screen
        with canvas(self.display) as draw:
            draw.text((5, 5), "Hello, World! "+str(self.counter), font=self.font, fill=self.TEXT_COLOR)

            # Draw bottom status text
            draw.text((5, 215), gps_status_text, font=self.font, fill=self.TEXT_COLOR)
        
            # Draw time in bottom right corner
            time_text = datetime.now().strftime("%H:%M")
            draw.text((265, 215), time_text, font=self.font, fill=self.TEXT_COLOR)
