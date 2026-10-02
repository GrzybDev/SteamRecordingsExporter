import unittest

from steamrecordingsexporter.helpers import get_filename, get_filename_pattern


class FilenameTemplateTests(unittest.TestCase):
    def test_replaces_identifiers_and_formats_numbers(self):
        self.assertEqual(
            get_filename("$RepresentationID$-$Number%05d$.m4s", RepresentationID="audio", Number=7),
            "audio-00007.m4s",
        )

    def test_escaped_dollars_are_literals(self):
        self.assertEqual(get_filename("$$Number$$-$$-$Number$", Number=7), "$Number$-$-7")

    def test_missing_identifier_is_reported(self):
        with self.assertRaisesRegex(KeyError, "RepresentationID"):
            get_filename("$RepresentationID$-$Number$", Number=7)

    def test_unsupported_identifiers_are_reported(self):
        for identifier in ("Time", "Bandwidth", "Other"):
            with self.subTest(identifier=identifier):
                with self.assertRaisesRegex(ValueError, "Unsupported DASH template identifier"):
                    get_filename(f"${identifier}$", **{identifier: 7})

    def test_invalid_format_is_not_silently_ignored(self):
        for fmt in ("%05q", "%5d", "%d", "%00d", "%s"):
            with self.subTest(fmt=fmt):
                with self.assertRaisesRegex(ValueError, "Unsupported DASH template format"):
                    get_filename(f"$Number{fmt}$", Number=7)

    def test_invalid_formatted_value_is_reported(self):
        with self.assertRaisesRegex(ValueError, "requires an integer"):
            get_filename("$Number%05d$", Number="bad")

    def test_malformed_templates_are_reported(self):
        for template in ("$Number", "Number$", "$-$", "$Number%$"):
            with self.subTest(template=template):
                with self.assertRaisesRegex(ValueError, "Malformed DASH template"):
                    get_filename(template, Number=7)

    def test_pattern_captures_number_and_escapes_literal_characters(self):
        pattern = get_filename_pattern("clips/$RepresentationID$.[v]-$Number$.m4s", RepresentationID="audio+")
        match = pattern.fullmatch("clips/audio+.[v]-42.m4s")
        self.assertIsNotNone(match)
        self.assertEqual(match.group("Number"), "42")
        self.assertIsNone(pattern.fullmatch("clips/audio.[v]-42.m4s"))
        self.assertIsNone(pattern.fullmatch("clips/audio+.[v]-42Xm4s"))
        self.assertIsNone(pattern.fullmatch("clips/audio+.[v]-42.m4s.extra"))

    def test_pattern_preserves_escaped_dollars(self):
        pattern = get_filename_pattern("$$Number$$-$Number$.m4s")
        self.assertEqual(pattern.fullmatch("$Number$-4.m4s").group("Number"), "4")

    def test_pattern_respects_minimum_formatted_width(self):
        pattern = get_filename_pattern("$Number%05d$.m4s")
        self.assertIsNone(pattern.fullmatch("7.m4s"))
        self.assertEqual(pattern.fullmatch("00007.m4s").group("Number"), "00007")
        self.assertEqual(pattern.fullmatch("123456.m4s").group("Number"), "123456")

    def test_pattern_requires_unresolved_number(self):
        for template in ("stream.m4s", "$$Number$$.m4s"):
            with self.subTest(template=template):
                with self.assertRaisesRegex(ValueError, "must contain"):
                    get_filename_pattern(template)
        with self.assertRaisesRegex(ValueError, "remain unresolved"):
            get_filename_pattern("$Number$.m4s", Number=7)

    def test_pattern_rejects_missing_other_values(self):
        with self.assertRaisesRegex(KeyError, "RepresentationID"):
            get_filename_pattern("$RepresentationID$-$Number$.m4s")

    def test_repeated_number_requires_the_same_value(self):
        pattern = get_filename_pattern("$Number$-$Number$.m4s")
        self.assertIsNotNone(pattern.fullmatch("7-7.m4s"))
        self.assertIsNone(pattern.fullmatch("7-8.m4s"))


if __name__ == "__main__":
    unittest.main()
