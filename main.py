from enum import Enum
from logging import getLogger, basicConfig, INFO
import time

from spherov2 import scanner
from spherov2.utils import ToyUtil
import pigpio

basicConfig(level=INFO)
logger = getLogger(__name__)

REMOTE_RASPBERRY_PI_ADDRESS = 'raspi.local' # デバッグ用

BTN_FORWARD_PIN = 20 # 前進
BTN_BACKWARD_PIN = 26 # 後退
BTN_CW_ROTATE_PIN = 16 # 上から見て時計回り
BTN_ACW_ROTATE_PIN = 21 # 上から見て反時計回り
BTN_DASH = 6 # 加速

BASE_SPEED = 80
MAX_SPEED = 255
ANGULAR_SPEED = 9

class TimeoutError(BaseException):
    ...


class SpheroStateEntry(Enum):
    STOP = 0
    FORWARD = 1
    BACKWARD = 2
    CW_ROTATE = 3
    ACW_ROTATE = 4


class SpheroState():
    def __init__(self):
        self.__state = SpheroStateEntry.STOP

    @property
    def state(self):
        return self.__state
    
    def acquire_controll(self, state: SpheroStateEntry) -> tuple[bool, bool]:
        """
        return (acquired, state_changed)
        """
        if self.__state == state:
            return (True, False)
        elif self.__state == SpheroStateEntry.STOP:
            self.__state = state
            return (True, True)
        return (False, False)
    
    def release_controll(self) -> SpheroStateEntry:
        if self.__state == SpheroStateEntry.STOP:
            logger.warning('release_controll called while not locked')
            return self.__state
        prev = self.__state
        self.__state = SpheroStateEntry.STOP
        return prev


class InputManager:
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


def main():
    btns = InputManager()
    # btns = FakeInputManager()

    logger.info('Start scanning...')
    with scanner.find_toy() as toy:
        logger.info(f'Connected to: {toy}')
        toy.wake()
        ToyUtil.set_robot_state_on_start(toy)
        ToyUtil.set_main_led(toy, 255, 255, 255, False)
        ToyUtil.set_back_led_brightness(toy, 255)

        angle = 0
        speed = 0
        state = SpheroState()

        last_controll_time = time.time()

        while True:
            try:
                if btns.btn_dash_pressed:
                    speed = MAX_SPEED
                else:
                    speed = BASE_SPEED

                if btns.btn_forward_pressed:
                    (acquire_controll, state_changed) = state.acquire_controll(SpheroStateEntry.FORWARD)

                    if acquire_controll and state_changed:
                        last_controll_time = time.time()
                        logger.debug(f"start {SpheroStateEntry.FORWARD} ({speed})")
                    ToyUtil.roll_start(toy, angle, speed)

                if btns.btn_backward_pressed:
                    (acquire_controll, state_changed) = state.acquire_controll(SpheroStateEntry.BACKWARD)

                    if acquire_controll and state_changed:
                        logger.debug(f"start {SpheroStateEntry.BACKWARD} ({speed})")
                        last_controll_time = time.time()
                    ToyUtil.roll_start(toy, (angle+180)%360, speed)

                if btns.btn_cw_pressed:
                    (acquire_controll, state_changed) = state.acquire_controll(SpheroStateEntry.CW_ROTATE)

                    if acquire_controll:
                        if state_changed:
                            logger.debug(f"start {SpheroStateEntry.CW_ROTATE}")
                            last_controll_time = time.time()
                        angle += ANGULAR_SPEED
                        angle %= 360
                        ToyUtil.roll_start(toy, angle, 0)

                if btns.btn_acw_pressed and state.acquire_controll(SpheroStateEntry.ACW_ROTATE):
                    (acquire_controll, state_changed) = state.acquire_controll(SpheroStateEntry.ACW_ROTATE)

                    if acquire_controll:
                        if state_changed:
                            logger.debug(f"start {SpheroStateEntry.ACW_ROTATE}")
                            last_controll_time = time.time()
                        angle -= ANGULAR_SPEED
                        angle %= 360
                        ToyUtil.roll_start(toy, angle, 0)


                if not True in {btns.btn_forward_pressed, btns.btn_backward_pressed, btns.btn_cw_pressed, btns.btn_acw_pressed}:
                    if state.state != SpheroStateEntry.STOP:
                        ToyUtil.roll_stop(toy, angle, False)
                        prev_state = state.release_controll()
                        logger.debug(f"stop {prev_state}")
                        last_controll_time = time.time()

                    else:
                        # STOP state
                        pass
                
                if (time.time() - last_controll_time > 60):
                    raise TimeoutError
                
                time.sleep(0.004)

            except Exception as e:
                logger.warning(f"{e}\nTerminated.")


if __name__ == '__main__':
    main()