import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ffmpeg import FFmpegError

from steamrecordingsexporter import export, remove_chunks
from steamrecordingsexporter.errors import ExportError
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
        maps = [
            run.arguments[i + 1] for i, argument in enumerate(run.arguments) if argument == "-map"
        ]
        self.assertEqual(maps, ["0", "1"])
        self.assertEqual(self.output.read_bytes(), b"MP4")
        self.assertEqual(contents(self.folder), before)
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ["clip", "clip.mp4"])
        self.assertFalse(run.inputs[0].parent.exists())

    def test_failed_merge_keeps_the_previous_output_and_the_recording(self):
        failures = {
            "could not merge": {"error": FFmpegError("Invalid data", [])},
            "empty file": {"output": b""},
        }
        before = contents(self.folder)
        for message, failure in failures.items():
            with self.subTest(message=message):
                self.output.write_bytes(b"EARLIER")
                with fake_ffmpeg(**failure) as runs, self.assertRaisesRegex(ExportError, message):
                    export(load_recording(self.folder), self.output)
                self.assertEqual(self.output.read_bytes(), b"EARLIER")
                self.assertEqual(contents(self.folder), before)
                self.assertEqual(
                    sorted(path.name for path in self.root.iterdir()), ["clip", "clip.mp4"]
                )
                self.assertFalse(runs[0].inputs[0].parent.exists())

    def test_refuses_outputs_that_would_overwrite_the_recording(self):
        hardlink = self.root / "hardlink.mp4"
        os.link(self.folder / "chunk-stream0-00001.m4s", hardlink)
        outputs = {
            self.folder / "session.mpd": "overwrite a file of the recording",
            self.folder / "init-stream1.m4s": "overwrite a file of the recording",
            hardlink: "overwrite a file of the recording",
            self.root / "missing" / "clip.mp4": "output folder does not exist",
        }
        before = contents(self.folder)
        for output, message in outputs.items():
            with self.subTest(output=output.name), fake_ffmpeg() as runs:
                with self.assertRaisesRegex(ExportError, message):
                    export(load_recording(self.folder), output)
                self.assertEqual(runs, [])
        self.assertEqual(contents(self.folder), before)

    def test_needs_ffmpeg_on_path(self):
        with (
            patch("shutil.which", return_value=None),
            self.assertRaisesRegex(ExportError, "FFmpeg was not found"),
        ):
            export(load_recording(self.folder), self.output)

    def test_removes_only_the_chunks_and_the_folders_they_leave_empty(self):
        folder = write_recording(
            self.root / "nested",
            {"0": [1, 2], "1": [1]},
            media="media/$RepresentationID$/$Number$.m4s",
        )
        (folder / "media" / "1" / "notes.txt").write_text("keep")
        (folder / "thumbnail.jpg").write_text("keep")
        self.assertEqual(remove_chunks(load_recording(folder)), {})
        self.assertEqual(
            sorted(contents(folder)), ["media/1/notes.txt", "session.mpd", "thumbnail.jpg"]
        )
        self.assertFalse((folder / "media" / "0").exists())

    def test_keeps_removing_past_a_chunk_it_cannot_delete(self):
        locked = self.folder / "chunk-stream0-00001.m4s"
        unlink = Path.unlink

        def unlink_unless_locked(path, *args, **kwargs):
            if path == locked:
                raise PermissionError("locked")
            unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", unlink_unless_locked):
            failures = remove_chunks(load_recording(self.folder))
        self.assertEqual(list(failures), [locked])
        self.assertEqual(sorted(contents(self.folder)), ["chunk-stream0-00001.m4s", "session.mpd"])


if __name__ == "__main__":
    unittest.main()
