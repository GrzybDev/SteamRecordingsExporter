import tempfile
import unittest
from pathlib import Path

from steamrecordingsexporter import export
from steamrecordingsexporter.recording import load_recording
from support import contents, fake_ffmpeg, write_recording


class ExportTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.folder = write_recording(self.root / "clip", {"0": [1, 2], "1": [1, 2]})
        self.output = self.root / "clip.mp4"

    def test_merges_the_joined_streams_into_the_output(self):
        before = contents(self.folder)
        with fake_ffmpeg() as runs:
            export(load_recording(self.folder), self.output)
        [run] = runs
        self.assertEqual(
            run.input_contents,
            [
                f"init-stream{rep_id}.m4s;chunk-stream{rep_id}-00001.m4s;"
                f"chunk-stream{rep_id}-00002.m4s;".encode()
                for rep_id in ("0", "1")
            ],
        )
        self.assertEqual(self.output.read_bytes(), b"MP4")
        self.assertEqual(contents(self.folder), before)
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["clip", "clip.mp4"])
        self.assertFalse(run.inputs[0].parent.exists())


if __name__ == "__main__":
    unittest.main()
