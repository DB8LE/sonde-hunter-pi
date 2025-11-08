import logging
import os
import queue
import tkinter as tk
from luma.core.device import device
from luma.core.interface.serial import spi, noop
from luma.core.render import canvas
from luma.lcd.device import ili9341
from PIL import Image, ImageFont, ImageTk
from threading import Thread


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
    def __init__(self,
                 driver: str,
                 width: int,
                 height: int,
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

    def update(self):
        with canvas(self.display) as draw:
            draw.text((0, 0), "Hello, World! "+str(self.counter), font=self.font, fill="white")
        
        self.counter += 1

