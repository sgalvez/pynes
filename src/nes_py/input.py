"""NES controller input state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class Button(IntEnum):
    """NES controller button order used by the serial shift register."""

    A = 0
    B = 1
    SELECT = 2
    START = 3
    UP = 4
    DOWN = 5
    LEFT = 6
    RIGHT = 7


@dataclass
class Controller:
    """NES controller with strobe and serial read behavior."""

    buttons: dict[Button, bool] = field(
        default_factory=lambda: {button: False for button in Button}
    )
    strobe: bool = False
    _latched_state: int = 0
    _shift_index: int = 0

    def set_button(self, button: Button, pressed: bool) -> None:
        self.buttons[button] = pressed
        if self.strobe:
            self._latch()

    def write_strobe(self, value: int) -> None:
        previous = self.strobe
        self.strobe = bool(value & 0x01)
        if self.strobe:
            self._latch()
        elif previous:
            self._latch()
            self._shift_index = 0

    def read(self) -> int:
        if self.strobe:
            self._latch()
            return self._latched_state & 0x01

        if self._shift_index >= 8:
            return 1

        value = (self._latched_state >> self._shift_index) & 0x01
        self._shift_index += 1
        return value

    def _latch(self) -> None:
        state = 0
        for button in Button:
            if self.buttons[button]:
                state |= 1 << int(button)
        self._latched_state = state
