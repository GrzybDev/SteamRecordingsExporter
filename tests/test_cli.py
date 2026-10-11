import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from steamrecordingsexporter import app
from support import fake_ffmpeg, write_recording


class CliTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.folder = write_recording(self.root / "clip", {"0": [1, 3], "1": [1, 2, 4, 5]})

    def run_cli(self, *arguments):
        with fake_ffmpeg():
            return CliRunner().invoke(app, [str(argument) for argument in arguments])

    def test_exports_and_counts_the_warnings(self):
        result = self.run_cli(self.folder, self.root)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Warning: Stream '0' is missing 1 of 3 segments (2)", result.output)
        self.assertIn("Warning: Stream '1' is missing 1 of 5 segments (3)", result.output)
        self.assertIn(f"Exported with 2 warnings: {self.root / 'clip.mp4'}", result.output)
        self.assertEqual((self.root / "clip.mp4").read_bytes(), b"MP4")

    def test_names_the_output_after_the_recording_unless_given_a_file(self):
        (self.root / "videos").mkdir()
        outputs = {
            None: self.root / "clip.mp4",
            self.root / "videos": self.root / "videos" / "clip.mp4",
            self.root / "named.mkv": self.root / "named.mkv",
        }
        for given, expected in outputs.items():
            with self.subTest(given=given), patch("pathlib.Path.cwd", return_value=self.root):
                result = self.run_cli(self.folder, *([given] if given else []))
                self.assertEqual(result.exit_code, 0, result.output)
                self.assertTrue(expected.is_file(), result.output)

    def test_reports_errors_with_a_failing_exit_code(self):
        (self.root / "empty").mkdir()
        result = self.run_cli(self.root / "empty")
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("Error: session.mpd was not found", result.output)
        self.assertNotIn("Exported", result.output)


if __name__ == "__main__":
    unittest.main()
