import xml.etree.ElementTree as ET
from typing import Dict, List, Optional


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

    def get_representations(self) -> List[Dict[str, Optional[str]]]:
        reps: List[Dict[str, Optional[str]]] = []

        for period in self.root.findall("mpd:Period", self.ns):
            for adaptation in period.findall("mpd:AdaptationSet", self.ns):
                for representation in adaptation.findall("mpd:Representation", self.ns):
                    rep_id = representation.get("id")
                    st = self._find_segment_template(representation, adaptation)
                    initialization = (
                        st.get("initialization") if st is not None else None
                    )
                    media = st.get("media") if st is not None else None
                    reps.append(
                        {"id": rep_id, "initialization": initialization, "media": media}
                    )

        return reps
