import unittest

from steamrecordingsexporter.mpd import MPD


def manifest(content):
    return f'<MPD xmlns="urn:mpeg:dash:schema:mpd:2011">{content}</MPD>'


def representation(rep_id="audio", template=None):
    if template is None:
        template = '<SegmentTemplate initialization="init-$RepresentationID$.m4s" media="$RepresentationID$-$Number$.m4s"/>'
    return f'<Representation id="{rep_id}">{template}</Representation>'


class ManifestTests(unittest.TestCase):
    def test_bytes_preserve_the_declared_xml_encoding(self):
        data = '<?xml version="1.0" encoding="ISO-8859-2"?>' + manifest(
            '<Period><AdaptationSet>' + representation('głos') + '</AdaptationSet></Period>'
        )
        self.assertEqual(MPD(data.encode('iso-8859-2')).get_representations()[0].id, 'głos')

    def test_nontrivial_base_urls_are_explicitly_rejected(self):
        data = manifest('<BaseURL>other-recording/</BaseURL><Period><AdaptationSet>'
                        + representation() + '</AdaptationSet></Period>')
        with self.assertRaisesRegex(ValueError, 'BaseURL paths are not supported'):
            MPD(data)

    def test_representation_ids_remain_strings(self):
        data = manifest("<Period><AdaptationSet>" + representation("01") + representation("audio") + "</AdaptationSet></Period>")
        reps = MPD(data).get_representations()
        self.assertEqual([rep.id for rep in reps], ["01", "audio"])
        self.assertEqual([rep.startNumber for rep in reps], [1, 1])

    def test_template_attributes_inherit_through_all_levels(self):
        data = manifest('''<Period>
            <SegmentTemplate initialization="init-$RepresentationID$.m4s" media="period-$Number$.m4s" startNumber="2"/>
            <AdaptationSet>
                <SegmentTemplate media="adaptation-$Number%05d$.m4s" startNumber="3"/>
                <Representation id="audio"><SegmentTemplate startNumber="4"/></Representation>
            </AdaptationSet>
        </Period>''')
        rep = MPD(data).get_representations()[0]
        self.assertEqual(rep.initialization, "init-$RepresentationID$.m4s")
        self.assertEqual(rep.media, "adaptation-$Number%05d$.m4s")
        self.assertEqual(rep.startNumber, 4)

    def test_duplicate_ids_are_rejected_across_adaptations(self):
        data = manifest("<Period><AdaptationSet>" + representation("audio") + "</AdaptationSet><AdaptationSet>" + representation("audio") + "</AdaptationSet></Period>")
        with self.assertRaisesRegex(ValueError, "Duplicate representation ID"):
            MPD(data).get_representations()

    def test_empty_ids_are_rejected(self):
        for element in (representation(""), representation(" "), "<Representation/>"):
            with self.subTest(element=element):
                with self.assertRaisesRegex(ValueError, "ID must not be empty"):
                    MPD(manifest(f"<Period><AdaptationSet>{element}</AdaptationSet></Period>")).get_representations()

    def test_empty_manifests_are_rejected(self):
        for content in ("", "<Period/>", "<Period><AdaptationSet/></Period>"):
            with self.subTest(content=content):
                with self.assertRaisesRegex(ValueError, "contains no"):
                    MPD(manifest(content)).get_representations()

    def test_multiple_periods_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Multiple DASH Period"):
            MPD(manifest("<Period/><Period/>")).get_representations()

    def test_wrong_xml_root_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Expected a DASH MPD"):
            MPD("<document/>")

    def test_missing_template_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Missing SegmentTemplate"):
            MPD(manifest('<Period><AdaptationSet><Representation id="audio"/></AdaptationSet></Period>')).get_representations()

    def test_missing_or_empty_template_attributes_are_rejected(self):
        for attrs in ('initialization="init.m4s"', 'media="$Number$.m4s"', 'initialization="" media="$Number$.m4s"'):
            with self.subTest(attrs=attrs):
                data = manifest("<Period><AdaptationSet>" + representation(template=f"<SegmentTemplate {attrs}/>") + "</AdaptationSet></Period>")
                with self.assertRaisesRegex(ValueError, "Missing required SegmentTemplate attributes"):
                    MPD(data).get_representations()

    def test_invalid_start_number_is_rejected(self):
        for number in ("", "bad", "-1"):
            with self.subTest(number=number):
                data = manifest("<Period><AdaptationSet>" + representation(template=f'<SegmentTemplate initialization="init.m4s" media="$Number$.m4s" startNumber="{number}"/>') + "</AdaptationSet></Period>")
                with self.assertRaisesRegex(ValueError, "startNumber"):
                    MPD(data).get_representations()

    def test_time_addressing_is_explicitly_rejected(self):
        data = manifest("<Period><AdaptationSet>" + representation(template='<SegmentTemplate initialization="init.m4s" media="$Time$.m4s"/>') + "</AdaptationSet></Period>")
        with self.assertRaisesRegex(ValueError, "Unsupported DASH template identifier: Time"):
            MPD(data).get_representations()

    def test_constant_media_template_is_rejected(self):
        data = manifest("<Period><AdaptationSet>" + representation(template='<SegmentTemplate initialization="init.m4s" media="chunk.m4s"/>') + "</AdaptationSet></Period>")
        with self.assertRaisesRegex(ValueError, "must contain"):
            MPD(data).get_representations()


if __name__ == "__main__":
    unittest.main()
