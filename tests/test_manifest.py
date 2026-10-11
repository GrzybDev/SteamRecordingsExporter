import unittest
from pathlib import Path

from steamrecordingsexporter.errors import ExportError
from steamrecordingsexporter.manifest import parse_manifest

STEAM_MANIFEST = Path(__file__).with_name("data") / "steam-session.mpd"

DEFAULT_TEMPLATE = '<SegmentTemplate initialization="init.m4s" media="$Number$.m4s"/>'


def manifest(period, attributes=""):
    return f'<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" {attributes}>{period}</MPD>'.encode()


def single(template=DEFAULT_TEMPLATE, representation_id="0"):
    return manifest(
        f'<Period><AdaptationSet><Representation id="{representation_id}">{template}'
        "</Representation></AdaptationSet></Period>"
    )


class ManifestTests(unittest.TestCase):
    def test_reads_a_steam_manifest(self):
        representations = parse_manifest(STEAM_MANIFEST.read_bytes())
        self.assertEqual([representation.id for representation in representations], ["0", "1"])
        for representation in representations:
            self.assertEqual(representation.start_number, 1155)
            self.assertEqual(representation.segment_count, 146)
            self.assertEqual(
                representation.initialization.format(representation.id),
                f"init-stream{representation.id}.m4s",
            )
            self.assertEqual(
                representation.media.format(representation.id, 1155),
                f"chunk-stream{representation.id}-01155.m4s",
            )

    def test_segment_template_is_inherited_down_to_the_representation(self):
        representation = parse_manifest(
            manifest(
                '<Period><SegmentTemplate initialization="init-$RepresentationID$.m4s"'
                ' media="period-$Number$.m4s" startNumber="2"/><AdaptationSet>'
                '<SegmentTemplate media="set-$Number%05d$.m4s" startNumber="3"/>'
                '<Representation id="a"><SegmentTemplate startNumber="4"/></Representation>'
                "</AdaptationSet></Period>"
            )
        )[0]
        self.assertEqual(representation.initialization.text, "init-$RepresentationID$.m4s")
        self.assertEqual(representation.media.text, "set-$Number%05d$.m4s")
        self.assertEqual(representation.start_number, 4)

    def test_counts_the_segments_that_fill_the_declared_duration(self):
        cases = {
            (
                'mediaPresentationDuration="PT1H52M42.109S"',
                'timescale="1000000" duration="3000000"',
            ): 2255,
            ('mediaPresentationDuration="PT6S"', 'duration="3"'): 2,
            ('mediaPresentationDuration="P1DT0.5S"', 'timescale="1000" duration="86400000"'): 2,
            ("", 'duration="3"'): None,
            ('mediaPresentationDuration="PT6S"', ""): None,
        }
        for (declared, timing), count in cases.items():
            with self.subTest(declared=declared, timing=timing):
                data = manifest(
                    '<Period><AdaptationSet><Representation id="0"><SegmentTemplate'
                    f' initialization="init.m4s" media="$Number$.m4s" {timing}/>'
                    "</Representation></AdaptationSet></Period>",
                    declared,
                )
                self.assertEqual(parse_manifest(data)[0].segment_count, count)

    def test_rejects_manifests_it_cannot_export(self):
        cases = {
            b"<MPD": "not valid XML",
            b"<document/>": "not a DASH MPD",
            manifest("<BaseURL>elsewhere/</BaseURL><Period/>"): "BaseURL",
            manifest("<Period/><Period/>"): "one Period, not 2",
            manifest("<Period><AdaptationSet/></Period>"): "no representations",
            single(representation_id=" "): "no ID",
            manifest(
                "<Period><AdaptationSet>"
                + f'<Representation id="0">{DEFAULT_TEMPLATE}</Representation>' * 2
                + "</AdaptationSet></Period>"
            ): "used more than once: 0",
            single("<SegmentTemplate media='$Number$.m4s'/>"): "no initialization",
            single("<SegmentTemplate initialization='init.m4s'/>"): "no media",
            single(
                '<SegmentTemplate initialization="init.m4s" media="https://cdn/$Number$.m4s"/>'
            ): "remote media",
            single('<SegmentTemplate initialization="init.m4s" media="$Time$.m4s"/>'): r"\$Time\$",
            single('<SegmentTemplate initialization="init.m4s" media="chunk.m4s"/>'): "must use",
            single(
                '<SegmentTemplate initialization="$Number$.m4s" media="$Number$.m4s"/>'
            ): "must not use",
            single(
                '<SegmentTemplate initialization="i.m4s" media="$Number$.m4s" startNumber="-1"/>'
            ): "invalid startNumber",
            manifest(
                '<Period><SegmentTemplate initialization="i" media="$Number$" duration="0"/>'
                '<AdaptationSet><Representation id="0"/></AdaptationSet></Period>',
                'mediaPresentationDuration="PT6S"',
            ): "invalid duration",
            manifest("<Period/>", 'mediaPresentationDuration="7 minutes"'): (
                "Invalid mediaPresentationDuration"
            ),
        }
        for data, message in cases.items():
            with self.subTest(message=message), self.assertRaisesRegex(ExportError, message):
                parse_manifest(data)


if __name__ == "__main__":
    unittest.main()
