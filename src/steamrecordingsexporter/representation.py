from dataclasses import dataclass
from typing import Optional

from steamrecordingsexporter.segments_data import SegmentData


@dataclass
class Representation:
    id: str
    initialization: str
    media: str
    startNumber: int

    segments: Optional[SegmentData] = None
