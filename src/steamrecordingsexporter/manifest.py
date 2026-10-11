import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass

from steamrecordingsexporter.errors import ExportError
from steamrecordingsexporter.template import Template

_NAMESPACES = {"mpd": "urn:mpeg:dash:schema:mpd:2011"}
_REMOTE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")


@dataclass(frozen=True)
class Representation:
    id: str
    initialization: Template
    media: Template
    start_number: int


def parse_manifest(data: bytes) -> list[Representation]:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ExportError(f"The manifest is not valid XML: {error}") from error
    if root.tag != f"{{{_NAMESPACES['mpd']}}}MPD":
        raise ExportError("The manifest is not a DASH MPD document")
    if any(
        (url.text or "").strip() not in ("", ".", "./")
        for url in root.iterfind(".//mpd:BaseURL", _NAMESPACES)
    ):
        raise ExportError("BaseURL paths are not supported")
    periods = root.findall("mpd:Period", _NAMESPACES)
    if len(periods) != 1:
        raise ExportError(f"The manifest must have one Period, not {len(periods)}")

    representations = [
        _representation((periods[0], adaptation, representation))
        for adaptation in periods[0].findall("mpd:AdaptationSet", _NAMESPACES)
        for representation in adaptation.findall("mpd:Representation", _NAMESPACES)
    ]
    if not representations:
        raise ExportError("The manifest has no representations")
    counts = Counter(representation.id for representation in representations)
    if duplicates := [id_ for id_, count in counts.items() if count > 1]:
        raise ExportError(f"Representation IDs used more than once: {', '.join(duplicates)}")
    return representations


def _representation(levels: tuple[ET.Element, ...]) -> Representation:
    """Read a representation, whose SegmentTemplate inherits from its period and set."""
    representation_id = levels[-1].get("id", "")
    if not representation_id.strip():
        raise ExportError("A representation has no ID")
    attributes: dict[str, str] = {}
    for level in levels:
        template = level.find("mpd:SegmentTemplate", _NAMESPACES)
        if template is not None:
            attributes.update(template.attrib)
    try:
        initialization = _template(attributes, "initialization")
        media = _template(attributes, "media")
        if initialization.uses_number:
            raise ValueError("the initialization template must not use $Number$")
        if not media.uses_number:
            raise ValueError("the media template must use $Number$")
        start_number = _integer(attributes.get("startNumber", "1"), "startNumber", minimum=0)
    except ValueError as error:
        raise ExportError(f"Representation {representation_id!r}: {error}") from error
    return Representation(representation_id, initialization, media, start_number)


def _template(attributes: dict[str, str], name: str) -> Template:
    text = attributes.get(name)
    if not text:
        raise ValueError(f"the SegmentTemplate has no {name}")
    if _REMOTE.match(text):
        raise ValueError(f"remote {name} paths are not supported: {text}")
    return Template(text)


def _integer(text: str, name: str, minimum: int) -> int:
    if not text.strip().isdecimal() or int(text) < minimum:
        raise ValueError(f"invalid {name} {text!r}")
    return int(text)
