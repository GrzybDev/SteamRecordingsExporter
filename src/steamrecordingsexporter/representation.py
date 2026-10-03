from dataclasses import dataclass


@dataclass
class Representation:
    id: str
    initialization: str
    media: str
    start_number: int

    segment_numbers: tuple[int, ...] = ()
