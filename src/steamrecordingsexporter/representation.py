from dataclasses import dataclass

from steamrecordingsexporter.segments_data import SegmentData


@dataclass
class Representation:
    id: int
    initialization: str
    media: str
    startNumber: int

    segments: SegmentData | None = None
