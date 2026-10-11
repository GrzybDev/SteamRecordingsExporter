import re
import xml.etree.ElementTree as ET
from typing import Union

from steamrecordingsexporter.representation import Representation
from steamrecordingsexporter.template import Template


_REMOTE_TEMPLATE_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")


class MPD:
    NAMESPACES = {"mpd": "urn:mpeg:dash:schema:mpd:2011"}

    def __init__(self, mpd_data: Union[str, bytes]):
        self.root = ET.fromstring(mpd_data.lstrip())
        if self.root.tag != f"{{{self.NAMESPACES['mpd']}}}MPD":
            raise ValueError("Expected a DASH MPD document")
        for base_url in self.root.iterfind(".//mpd:BaseURL", self.NAMESPACES):
            if (base_url.text or "").strip() not in ("", ".", "./"):
                raise ValueError("DASH BaseURL paths are not supported; use local SegmentTemplate paths")

    def _segment_template_attributes(
        self, period: ET.Element, adaptation: ET.Element, representation: ET.Element
    ) -> dict[str, str]:
        attributes: dict[str, str] = {}
        found_template = False
        for element in (period, adaptation, representation):
            template = element.find("mpd:SegmentTemplate", self.NAMESPACES)
            if template is not None:
                found_template = True
                attributes.update(template.attrib)
        if not found_template:
            raise ValueError(
                f"Missing SegmentTemplate for representation ID: {representation.get('id')}"
            )
        return attributes

    def get_representations(self) -> list[Representation]:
        periods = self.root.findall("mpd:Period", self.NAMESPACES)
        if len(periods) > 1:
            raise ValueError("Multiple DASH Period elements are not supported")
        if not periods:
            raise ValueError("MPD contains no Period elements")

        reps: list[Representation] = []
        representation_ids = set()
        period = periods[0]
        for adaptation in period.findall("mpd:AdaptationSet", self.NAMESPACES):
            for representation in adaptation.findall("mpd:Representation", self.NAMESPACES):
                rep_id = representation.get("id")
                if rep_id is None or not rep_id.strip():
                    raise ValueError("Representation ID must not be empty")
                if rep_id in representation_ids:
                    raise ValueError(f"Duplicate representation ID: {rep_id}")
                representation_ids.add(rep_id)

                attributes = self._segment_template_attributes(
                    period, adaptation, representation
                )
                initialization = attributes.get("initialization")
                media = attributes.get("media")
                if not initialization or not media:
                    raise ValueError(
                        f"Missing required SegmentTemplate attributes for representation ID: {rep_id}"
                    )
                for name, template in (("initialization", initialization), ("media", media)):
                    if _REMOTE_TEMPLATE_PATTERN.match(template):
                        raise ValueError(
                            f"Remote {name} template path is not supported; "
                            f"use a local path for representation ID: {rep_id}"
                        )

                try:
                    start_number = int(attributes.get("startNumber", "1"))
                except ValueError as exc:
                    raise ValueError(
                        f"Invalid startNumber for representation ID: {rep_id}"
                    ) from exc
                if start_number < 0:
                    raise ValueError(
                        f"startNumber must be non-negative for representation ID: {rep_id}"
                    )

                initialization_template = Template(initialization)
                media_template = Template(media)
                if initialization_template.uses_number:
                    raise ValueError("Initialization template must not use $Number$")
                if not media_template.uses_number:
                    raise ValueError("Media template must use $Number$")
                reps.append(
                    Representation(
                        id=rep_id,
                        initialization=initialization_template,
                        media=media_template,
                        start_number=start_number,
                    )
                )

        if not reps:
            raise ValueError("MPD contains no representations")
        return reps
