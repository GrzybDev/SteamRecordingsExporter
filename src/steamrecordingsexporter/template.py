import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

_NUMBER = re.compile(r"Number(?:%0([1-9][0-9]*)d)?")


@dataclass(frozen=True)
class _Identifier:
    name: str
    width: int = 1

    def resolve(self, representation_id: str, number: int | None) -> str:
        if self.name == "RepresentationID":
            return representation_id
        return str(number).zfill(self.width)

    def pattern(self, representation_id: str) -> str:
        if self.name == "RepresentationID":
            return re.escape(representation_id)
        return "([0-9]+)"


class Template:
    """A SegmentTemplate path with the $RepresentationID$, $Number$ and $$ identifiers of DASH."""

    def __init__(self, text: str) -> None:
        self._parts = tuple(_parse(text))

    @property
    def uses_number(self) -> bool:
        return any(isinstance(part, _Identifier) and part.name == "Number" for part in self._parts)

    def format(self, representation_id: str, number: int | None = None) -> str:
        return "".join(
            part if isinstance(part, str) else part.resolve(representation_id, number)
            for part in self._parts
        )

    def numbers(self, representation_id: str, names: Iterable[str]) -> set[int]:
        """Return the segment numbers of the names that this template gives the representation."""
        pattern = re.compile(
            "".join(
                re.escape(part) if isinstance(part, str) else part.pattern(representation_id)
                for part in self._parts
            )
        )
        numbers = set()
        for name in names:
            match = pattern.fullmatch(name)
            # Only the exact spelling counts, so "7" and "007" are not both taken as segment 7.
            if match and self.format(representation_id, int(match[1])) == name:
                numbers.add(int(match[1]))
        return numbers


def _parse(text: str) -> Iterator[str | _Identifier]:
    pieces = text.split("$")
    if len(pieces) % 2 == 0:
        raise ValueError(f"unbalanced $ in {text!r}")
    for index, piece in enumerate(pieces):
        if index % 2 == 0:
            if piece:
                yield piece
        elif not piece:
            yield "$"
        elif piece == "RepresentationID":
            yield _Identifier(piece)
        elif match := _NUMBER.fullmatch(piece):
            yield _Identifier("Number", int(match[1] or 1))
        else:
            raise ValueError(f"unsupported identifier ${piece}$ in {text!r}")
