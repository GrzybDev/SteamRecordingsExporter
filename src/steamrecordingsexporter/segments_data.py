from dataclasses import dataclass


@dataclass(frozen=True)
class SegmentData:
    numbers: tuple[int, ...]
