import math
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction

from steamrecordingsexporter import messages
from steamrecordingsexporter.errors import ExportError
from steamrecordingsexporter.template import Template

_NAMESPACES = {"mpd": "urn:mpeg:dash:schema:mpd:2011"}
_REMOTE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
_DURATION = re.compile(
    r"P(?:(?P<days>[0-9]+)D)?"
    r"(?:T(?:(?P<hours>[0-9]+)H)?(?:(?P<minutes>[0-9]+)M)?(?:(?P<seconds>[0-9]+(?:\.[0-9]+)?)S)?)?"
)


@dataclass(frozen=True)
class Representation:
    """A stream of the manifest with the templates that name its chunks.

    Attributes:
        segment_count: How many segments fill the declared duration, or None when the
            manifest declares no duration.
    """

    id: str
    initialization: Template
    media: Template
    start_number: int
    segment_count: int | None


def parse_manifest(data: bytes) -> list[Representation]:
    """Read the representations of a DASH manifest that the export supports.

    Args:
        data: The bytes of the manifest.

    Raises:
        ExportError: If the manifest is invalid or uses a feature the export does not
            support.
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ExportError(messages.INVALID_XML.format(error=error)) from error
    if root.tag != f"{{{_NAMESPACES['mpd']}}}MPD":
        raise ExportError(messages.NOT_MPD)
    if any(
        (url.text or "").strip() not in ("", ".", "./")
        for url in root.iterfind(".//mpd:BaseURL", _NAMESPACES)
    ):
        raise ExportError(messages.BASE_URL)
    periods = root.findall("mpd:Period", _NAMESPACES)
    if len(periods) != 1:
        raise ExportError(messages.PERIOD_COUNT.format(count=len(periods)))

    duration = root.get("mediaPresentationDuration")
    seconds = _seconds(duration) if duration else None
    representations = [
        _representation((periods[0], adaptation, representation), seconds)
        for adaptation in periods[0].findall("mpd:AdaptationSet", _NAMESPACES)
        for representation in adaptation.findall("mpd:Representation", _NAMESPACES)
    ]
    if not representations:
        raise ExportError(messages.NO_REPRESENTATIONS)
    counts = Counter(representation.id for representation in representations)
    if duplicates := [id_ for id_, count in counts.items() if count > 1]:
        raise ExportError(messages.DUPLICATE_IDS.format(ids=", ".join(duplicates)))
    return representations


def _representation(levels: tuple[ET.Element, ...], seconds: Fraction | None) -> Representation:
    """Read a representation, whose SegmentTemplate inherits from its period and set."""
    representation_id = levels[-1].get("id", "")
    if not representation_id.strip():
        raise ExportError(messages.NO_ID)
    attributes: dict[str, str] = {}
    for level in levels:
        template = level.find("mpd:SegmentTemplate", _NAMESPACES)
        if template is not None:
            attributes.update(template.attrib)
    try:
        initialization = _template(attributes, "initialization")
        media = _template(attributes, "media")
        if initialization.uses_number:
            raise ValueError(messages.INITIALIZATION_NUMBER)
        if not media.uses_number:
            raise ValueError(messages.MEDIA_NUMBER)
        start_number = _integer(attributes.get("startNumber", "1"), "startNumber", minimum=0)
        segment_count = _segment_count(attributes, seconds)
    except ValueError as error:
        raise ExportError(
            messages.REPRESENTATION_PROBLEM.format(id=representation_id, problem=error)
        ) from error
    return Representation(representation_id, initialization, media, start_number, segment_count)


def _template(attributes: dict[str, str], name: str) -> Template:
    text = attributes.get(name)
    if not text:
        raise ValueError(messages.TEMPLATE_MISSING.format(name=name))
    if _REMOTE.match(text):
        raise ValueError(messages.REMOTE_TEMPLATE.format(name=name, text=text))
    return Template(text)


def _segment_count(attributes: dict[str, str], seconds: Fraction | None) -> int | None:
    """Return how many segments of the template's duration fill the recording, as DASH counts."""
    if seconds is None or "duration" not in attributes:
        return None
    timescale = _integer(attributes.get("timescale", "1"), "timescale", minimum=1)
    duration = _integer(attributes["duration"], "duration", minimum=1)
    return math.ceil(seconds * timescale / duration)


def _seconds(duration: str) -> Fraction:
    """Return the length of an ISO 8601 duration such as PT1H2M3.5S in seconds."""
    match = _DURATION.fullmatch(duration.strip())
    if not match:
        raise ExportError(messages.INVALID_DURATION.format(duration=duration))
    days, hours, minutes = (int(match[unit] or 0) for unit in ("days", "hours", "minutes"))
    return ((days * 24 + hours) * 60 + minutes) * 60 + Fraction(match["seconds"] or 0)


def _integer(text: str, name: str, minimum: int) -> int:
    """Return the decimal attribute value, refusing one below the minimum."""
    if not text.strip().isdecimal() or int(text) < minimum:
        raise ValueError(messages.INVALID_VALUE.format(name=name, text=text))
    return int(text)
