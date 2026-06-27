from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class MarginLeverageCheck:
    passed: bool
    rejections: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class MarginLeverageManager:
    def __init__(self, *, expected_margin_mode: str, expected_leverage: int) -> None:
        self.expected_margin_mode = expected_margin_mode
        self.expected_leverage = int(expected_leverage)

    def check(self, *, observed_margin_mode: str, observed_leverage: int) -> MarginLeverageCheck:
        rejections: list[str] = []
        if observed_margin_mode != self.expected_margin_mode:
            rejections.append("margin_mode_mismatch")
        if int(observed_leverage) != self.expected_leverage:
            rejections.append("leverage_mismatch")
        return MarginLeverageCheck(not rejections, rejections)
