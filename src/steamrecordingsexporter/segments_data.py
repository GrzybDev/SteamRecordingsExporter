from dataclasses import dataclass


@dataclass(frozen=True)
class SegmentData:
    """Available media segment numbers in playback order, including gaps."""

    numbers: tuple[int, ...]
