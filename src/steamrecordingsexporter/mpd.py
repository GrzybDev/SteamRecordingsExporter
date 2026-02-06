import xml.etree.ElementTree as ET
from typing import List, Optional

from steamrecordingsexporter.representation import Representation


class MPD:
    def __init__(self, mpd_data: str):
        self.ns = {"mpd": "urn:mpeg:dash:schema:mpd:2011"}
        self.root = ET.fromstring(mpd_data.lstrip())

    def _find_segment_template(
        self, representation: ET.Element, adaptation: Optional[ET.Element]
    ) -> Optional[ET.Element]:
        st = representation.find("mpd:SegmentTemplate", self.ns)

        if st is None and adaptation is not None:
            st = adaptation.find("mpd:SegmentTemplate", self.ns)

        return st

    def get_representations(self) -> List[Representation]:
        reps: List[Representation] = []

        for period in self.root.findall("mpd:Period", self.ns):
            for adaptation in period.findall("mpd:AdaptationSet", self.ns):
                for representation in adaptation.findall("mpd:Representation", self.ns):
                    rep_id = representation.get("id")
                    st = self._find_segment_template(representation, adaptation)

                    if st is not None:
                        initialization = st.get("initialization")
                        media = st.get("media")
                        startNumber = st.get("startNumber") or "1"
                    else:
                        raise ValueError(
                            f"Missing SegmentTemplate for representation ID: {rep_id}"
                        )

                    if rep_id is None or initialization is None or media is None:
                        raise ValueError(
                            f"Missing required attributes for representation ID: {rep_id}"
                        )

                    reps.append(
                        Representation(
                            id=int(rep_id),
                            initialization=initialization,
                            media=media,
                            startNumber=int(startNumber),
                        )
                    )

        return reps
