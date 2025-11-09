import logging
import spidev
import time
from gpiozero import Button, Device, DigitalOutputDevice
from gpiozero.pins.pigpio import PiGPIOFactory
from typing import Callable, Deque, Literal, Optional, Tuple

Device.pin_factory = PiGPIOFactory()

class Xpt2046:
    # Commands from ILI9341 datasheet
    GET_X = 0b11010000  # X position
    GET_Y = 0b10010000  # Y position
    GET_Z1 = 0b10110000  # Z1 position
    GET_Z2 = 0b11000000  # Z2 position

    def __init__(
            self,
            spi_bus: int,
            spi_device: int,
            cs_pin: int,
            display_width: int,
            display_height: int,
            min_x: int = 100,
            max_x: int = 1962,
            min_y: int = 100,
            max_y: int = 1900,
            irq_pin: Optional[Button] = None,
            irq_handler: Optional[Callable[[int, int], None]] = None
        ):
        
        self.spi = spidev.SpiDev()
        self.spi.open(spi_bus, spi_device)
        self.spi.max_speed_hz = 2000000
        self.spi.mode = 0b00

        self.cs = DigitalOutputDevice(cs_pin, active_high=False, initial_value=True)

        self.width = display_width
        self.height = display_height
        self.min_x = min_x
        self.max_x = max_x
        self.min_y = min_y
        self.max_y = max_y

        self.x_multiplier = display_width / (max_x - min_x)
        self.x_add = min_x * -self.x_multiplier
        self.y_multiplier = display_height / (max_y - min_y)
        self.y_add = min_y * -self.y_multiplier

        if irq_pin is not None:
            self.irq_pin = irq_pin
            self.irq_handler = irq_handler
            self.irq_locked = False
            self.irq_pin.when_pressed = self.irq_press
            self.irq_pin.when_released = self.irq_release

    def get_touch(self):
        """Take multiple samples to get accurate touch reading."""

        timeout = 2  # Seconds
        confidence = 5
        buffer = [(0, 0) for _ in range(confidence)]
        buffer_length = confidence
        buffer_index = 0
        nsamples = 0

        while timeout > 0:
            if nsamples == buffer_length:
                meanx = sum(c[0] for c in buffer) // buffer_length
                meany = sum(c[1] for c in buffer) // buffer_length
                dev = sum((c[0] - meanx) ** 2 + (c[1] - meany) ** 2 for c in buffer) / buffer_length
                if dev <= 50:
                    return self.normalize(meanx, meany)

            sample = self.raw_touch()
            if sample is None:
                nsamples = 0
            else:
                buffer[buffer_index] = sample
                buffer_index = (buffer_index + 1) % buffer_length
                nsamples = min(nsamples + 1, buffer_length)

            time.sleep(0.05)
            timeout -= 0.05

        return None

    def irq_press(self):
        """Handle interrupt press"""

        if not self.irq_locked:
            self.irq_locked = True
            buff = self.raw_touch()
            if buff is not None:
                x, y = self.normalize(*buff)
                if self.irq_handler:
                    self.irq_handler(x, y)
            time.sleep(0.1)

    def irq_release(self):
        """Handle interrupt release"""

        if self.irq_locked:
            time.sleep(0.1)
            self.irq_locked = False

    def normalize(self, x, y):
        """Normalize raw X,Y values to screen coordinates"""

        x = int(self.x_multiplier * x + self.x_add)
        y = int(self.y_multiplier * y + self.y_add)

        return x, y

    def raw_touch(self):
        """Read raw touch coordinates"""

        x = self.send_command(self.GET_X)
        y = self.send_command(self.GET_Y)

        if self.min_x <= x <= self.max_x and self.min_y <= y <= self.max_y:
            return x, y
        
        return None

    def send_command(self, command):
        """Send a command to the touch controller and read the response"""

        self.cs.on()
        response = self.spi.xfer2([command, 0x00, 0x00])
        self.cs.off()

        return ((response[1] << 4) | (response[2] >> 4))
    
class TouchController:
    def __init__(
            self,
            driver: Literal["XPT2046"],
            spi_port: int,
            spi_device: int,
            cs_pin: int,
            irq_pin: int,
            display_width: int,
            display_height: int,
            output_queue: Deque[Tuple[int, int]]
        ) -> None:
        
        self._irq_button = None
        if driver == "XPT2046":
            self._irq_button = Button(irq_pin)

            Xpt2046(
                spi_bus=spi_port,
                spi_device=spi_device,
                cs_pin=cs_pin,
                display_width=display_width,
                display_height=display_height,
                irq_pin=self._irq_button,
                irq_handler=self._interrupt_handler
            )
        else:
            logging.error("Unsupported touch driver: "+driver)
            exit(1)

        self.out_queue = output_queue

    def _interrupt_handler(self, x: int, y: int):
        """Handle a touchscreen interrupt"""

        self.out_queue.append((x, y))

    def close(self):
        if self._irq_button is not None:
            self._irq_button.close()
