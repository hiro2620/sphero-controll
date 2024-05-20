from enum import Enum
from logging import getLogger, basicConfig, INFO, DEBUG
import subprocess
import time

import adafruit_ssd1306
import board
import busio
from spherov2 import scanner
from spherov2.utils import ToyUtil
from spherov2.scanner import ToyNotFoundError
import pigpio
from PIL import ImageFont, Image, ImageDraw


basicConfig(level=INFO)
logger = getLogger(__name__)
logger.setLevel(DEBUG)

REMOTE_RASPBERRY_PI_ADDRESS = 'raspi.local' # デバッグ用

BTN_FORWARD_PIN = 16 # 前進
BTN_BACKWARD_PIN = 6 # 後退
BTN_CW_ROTATE_PIN = 26 # 上から見て時計回り
BTN_ACW_ROTATE_PIN = 24 # 上から見て反時計回り
BTN_DASH = 22 # 加速

LED_FORWARD_PIN = 12
LED_BACKWARD_PIN = 5
LED_CW_ROTATE_PIN = 13
LED_ACW_ROTATE_PIN = 23
LED_DASH_PIN = 27

BASE_SPEED = 120
MAX_SPEED = 255
ANGULAR_SPEED = 12

MAX_INTERVAL = 60

class TimeoutError(BaseException):
    ...


class SpheroStates(Enum):
    STOP = 0
    FORWARD = 1
    BACKWARD = 2
    CW_ROTATE = 3
    ACW_ROTATE = 4


class SpheroStateManager():
    def __init__(self):
        self.__state = SpheroStates.STOP

    @property
    def state(self):
        return self.__state
    
    def acquire_controll(self, state: SpheroStates) -> tuple[bool, bool]:
        """
        return (acquired, state_changed)
        """
        if self.__state == state:
            return (True, False)
        elif self.__state == SpheroStates.STOP:
            self.__state = state
            return (True, True)
        return (False, False)
    
    def release_controll(self) -> SpheroStates:
        if self.__state == SpheroStates.STOP:
            logger.warning('release_controll called while not locked')
            return self.__state
        prev = self.__state
        self.__state = SpheroStates.STOP
        return prev


class IOManager:
    def __init__(self, remote=False):
        if remote:
            self.__pi = pigpio.pi(REMOTE_RASPBERRY_PI_ADDRESS)
        else:
            self.__pi = pigpio.pi()

        if not self.__pi.connected:
            raise ConnectionError('Failed to connect to pigpio daemon')

        self.__pi.set_pull_up_down(BTN_FORWARD_PIN, pigpio.PUD_UP)
        self.__pi.set_pull_up_down(BTN_BACKWARD_PIN, pigpio.PUD_UP)
        self.__pi.set_pull_up_down(BTN_CW_ROTATE_PIN, pigpio.PUD_UP)
        self.__pi.set_pull_up_down(BTN_ACW_ROTATE_PIN, pigpio.PUD_UP)
        self.__pi.set_pull_up_down(BTN_DASH, pigpio.PUD_UP)
        self.__pi.set_mode(LED_FORWARD_PIN, pigpio.OUTPUT)
        self.__pi.set_mode(LED_BACKWARD_PIN, pigpio.OUTPUT)
        self.__pi.set_mode(LED_CW_ROTATE_PIN, pigpio.OUTPUT)
        self.__pi.set_mode(LED_ACW_ROTATE_PIN, pigpio.OUTPUT)
        self.__pi.set_mode(LED_DASH_PIN, pigpio.OUTPUT)

    
    @property
    def btn_forward_pressed(self):
        return not self.__pi.read(BTN_FORWARD_PIN)

    @property
    def btn_backward_pressed(self):
        return not self.__pi.read(BTN_BACKWARD_PIN)

    @property
    def btn_cw_pressed(self):
        return not self.__pi.read(BTN_CW_ROTATE_PIN)

    @property
    def btn_acw_pressed(self):
        return not self.__pi.read(BTN_ACW_ROTATE_PIN)
    
    @property
    def btn_dash_pressed(self):
        return not self.__pi.read(BTN_DASH)
    
    def set_led(self, pin, value):
        self.__pi.write(pin, value)


class DisplayStates(Enum):
    INITIALIZING = 0
    RUNNING = 1
    TERMINATED = 2

class DisplayManager:
    WIDTH = 128
    HEIGHT = 64

    PADDING_TOP = 20
    PADDING_LEFT = 0

    def __init__(self):
        i2c = busio.I2C(board.SCL, board.SDA)
        self.__oled = adafruit_ssd1306.SSD1306_I2C(self.WIDTH, self.HEIGHT, i2c, addr=0x3c)
        self.__oled.fill(0)
        self.__oled.show()


    def __del__(self):
        self.clear()


    @staticmethod
    def get_undervoltage_state():
        r = int(subprocess.run(['vcgencmd', 'get_throttled'], stdout=subprocess.PIPE).stdout.decode('utf-8')[12:], 16)
        return r & 0x50000 != 0


    def clear(self):
        self.__oled.fill(0)
        self.__oled.show()


    def __draw_header(self, draw: ImageDraw):
        if self.get_undervoltage_state():
            draw.rectangle([(108, 0), (124, 10)], width=1, fill=0, outline=255)
            draw.rectangle([(124, 3), (128, 7)], width=0, fill=255)
            draw.polygon([(108, 0), (116, 10), (108, 10)], width=0, fill=255)


    def display_scanning(self):
        font = ImageFont.load_default()
        image = Image.new("1", (self.WIDTH, self.HEIGHT))
        draw = ImageDraw.Draw(image)
        draw.text((self.PADDING_LEFT, self.PADDING_TOP), 'Scanning...', font=font, fill=255)
        self.__draw_header(draw)
        self.__oled.image(image)
        self.__oled.show()


    def display_running(self, name:str="anonymous sphero", mac_address:str=""):
        font = ImageFont.load_default()
        image = Image.new("1", (self.WIDTH, self.HEIGHT))
        draw = ImageDraw.Draw(image)
        draw.text((self.PADDING_LEFT, self.PADDING_TOP), f"Ready [{name}]", font=font, fill=255)
        draw.text((self.PADDING_LEFT, self.PADDING_TOP + 16), mac_address, font=font, fill=255)
        self.__draw_header(draw)
        self.__oled.image(image)
        self.__oled.show()


    def display_not_found(self):
        font = ImageFont.load_default()
        image = Image.new("1", (self.WIDTH, self.HEIGHT))
        draw = ImageDraw.Draw(image)
        draw.text((self.PADDING_LEFT, self.PADDING_TOP), 'No Sphero found.', font=font, fill=180)
        self.__draw_header(draw)
        self.__oled.image(image)
        self.__oled.show()


    def display_terminated(self):
        font = ImageFont.load_default()
        image = Image.new("1", (self.WIDTH, self.HEIGHT))
        draw = ImageDraw.Draw(image)
        draw.text((self.PADDING_LEFT, self.PADDING_TOP), 'Terminated.', font=font, fill=180)
        draw.text((self.PADDING_LEFT, self.PADDING_TOP + 16), 'Restart in few seconds.', font=font, fill=180)
        self.__draw_header(draw)
        self.__oled.image(image)
        self.__oled.show()


def main():
    display = DisplayManager()
    interfaces = IOManager()

    logger.info('Start scanning...')
    display.display_scanning()

    try:
        with scanner.find_toy() as toy:
            logger.info(f'Connected to: {toy}')
            display.display_running(name=toy.name, mac_address=toy.address)

            toy.wake()
            ToyUtil.set_robot_state_on_start(toy)
            ToyUtil.set_main_led(toy, 255, 255, 255, False)
            ToyUtil.set_back_led_brightness(toy, 255)

            angle = 0
            speed = 0
            state = SpheroStateManager()

            last_controll_time = time.time()
            skip_press_continue = 0

            interfaces.set_led(LED_FORWARD_PIN, 1)
            interfaces.set_led(LED_BACKWARD_PIN, 1)
            interfaces.set_led(LED_CW_ROTATE_PIN, 1)
            interfaces.set_led(LED_ACW_ROTATE_PIN, 1)
            interfaces.set_led(LED_DASH_PIN, 1)

            while True:
                pressed = False
                pressed_skip = True
                try:
                    if interfaces.btn_dash_pressed:
                        pressed = True
                        speed = MAX_SPEED
                    else:
                        speed = BASE_SPEED

                    if interfaces.btn_forward_pressed:
                        pressed = True
                        (acquire_controll, state_changed) = state.acquire_controll(SpheroStates.FORWARD)

                        if acquire_controll and state_changed:
                            last_controll_time = time.time()
                            logger.debug(f"start {SpheroStates.FORWARD} ({speed})")
                        ToyUtil.roll_start(toy, angle, speed)
                    else:
                        pressed_skip = False

                    if interfaces.btn_backward_pressed:
                        pressed = True
                        (acquire_controll, state_changed) = state.acquire_controll(SpheroStates.BACKWARD)

                        if acquire_controll and state_changed:
                            logger.debug(f"start {SpheroStates.BACKWARD} ({speed})")
                            last_controll_time = time.time()
                        ToyUtil.roll_start(toy, (angle+180)%360, speed)
                    else:
                        pressed_skip = False

                    if interfaces.btn_cw_pressed:
                        pressed = True
                        (acquire_controll, state_changed) = state.acquire_controll(SpheroStates.CW_ROTATE)

                        if acquire_controll:
                            if state_changed:
                                logger.debug(f"start {SpheroStates.CW_ROTATE}")
                                last_controll_time = time.time()
                            angle += ANGULAR_SPEED
                            angle %= 360
                            ToyUtil.roll_start(toy, angle, 0)

                    if interfaces.btn_acw_pressed and state.acquire_controll(SpheroStates.ACW_ROTATE):
                        pressed = True
                        (acquire_controll, state_changed) = state.acquire_controll(SpheroStates.ACW_ROTATE)

                        if acquire_controll:
                            if state_changed:
                                logger.debug(f"start {SpheroStates.ACW_ROTATE}")
                                last_controll_time = time.time()
                            angle -= ANGULAR_SPEED
                            angle %= 360
                            ToyUtil.roll_start(toy, angle, 0)
                    
                    if pressed_skip:
                        skip_press_continue += 1
                        if skip_press_continue > 100:
                            break
                    
                    if not pressed:
                        if state.state != SpheroStates.STOP:
                            ToyUtil.roll_stop(toy, angle, False)
                            prev_state = state.release_controll()
                            logger.debug(f"stop {prev_state}")
                            last_controll_time = time.time()

                        else:
                            # STOP state
                            pass
                    
                    if (time.time() - last_controll_time > MAX_INTERVAL):
                        raise TimeoutError
                    
                    time.sleep(0.004)

                except Exception as e:
                    logger.warning(f"{e}\nbreak loop..")
                    break

    except ToyNotFoundError as e:
        logger.warning('Sphero not found.')
        display.display_not_found()
        time.sleep(3)

    finally:
        logger.warning(f"Terminated.")
        display.display_terminated()
        time.sleep(5)


if __name__ == '__main__':
    main()