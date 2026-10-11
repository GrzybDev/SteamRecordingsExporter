from dataclasses import dataclass

from steamrecordingsexporter.template import Template


@dataclass(frozen=True)
class Representation:
    id: str
    initialization: Template
    media: Template
    start_number: int

    segment_numbers: tuple[int, ...] = ()
