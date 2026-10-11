import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from steamrecordingsexporter.errors import ExportError
from steamrecordingsexporter.recording import load_recording
from support import write_recording


class RecordingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.folder = Path(directory.name, "clip")

    def test_loads_each_stream_with_its_chunks_in_order(self):
        folder = write_recording(
            self.folder,
            {"0": [2, 1, 3], "audio": [1, 2, 3]},
            media="$RepresentationID$/$Number$.m4s",
        )
        recording = load_recording(self.folder)
        self.assertEqual(recording.folder, folder)
        self.assertEqual([stream.id for stream in recording.streams], ["0", "audio"])
        for stream in recording.streams:
            self.assertEqual(
                [path.relative_to(folder).as_posix() for path in stream.chunks],
                [f"init-stream{stream.id}.m4s", *(f"{stream.id}/{n}.m4s" for n in (1, 2, 3))],
            )
            self.assertEqual(stream.missing, ())

    def test_counts_the_segments_missing_from_each_stream(self):
        write_recording(self.folder, {"0": [5, 6, 8, 11], "1": [7, 8]}, start_number=5)
        recording = load_recording(self.folder)
        self.assertEqual([stream.missing for stream in recording.streams], [(7, 9, 10), (5, 6)])
        self.assertEqual(len(recording.streams[0].segments), 4)

    def test_counts_segments_missing_up_to_the_last_one_the_manifest_declares(self):
        write_recording(
            self.folder,
            {"0": [1, 2, 3], "1": [1, 2, 3, 4, 5], "2": [1, 2, 3, 4, 5, 6]},
            duration="PT14.5S",
            segment_duration=3,
        )
        recording = load_recording(self.folder)
        self.assertEqual([stream.missing for stream in recording.streams], [(4, 5), (), ()])
        self.assertEqual(len(recording.streams[2].segments), 6)

    def test_ignores_files_that_are_not_segments_of_the_stream(self):
        write_recording(self.folder, {"0": [1, 2]})
        for name in (
            "chunk-stream0-3.m4s",
            "chunk-stream0-00000.m4s",
            "chunk-stream0-00004.m4s.part",
            "chunk-stream1-00005.m4s",
            "thumbnail.jpg",
        ):
            (self.folder / name).write_bytes(b"other")
        stream = load_recording(self.folder).streams[0]
        self.assertEqual(
            [path.name for path in stream.segments],
            ["chunk-stream0-00001.m4s", "chunk-stream0-00002.m4s"],
        )
        self.assertEqual(stream.missing, ())

    def test_lists_a_shared_initialization_chunk_once(self):
        folder = write_recording(self.folder, {"0": [1], "1": [1]}, initialization="init.m4s")
        self.assertEqual(
            load_recording(self.folder).chunks,
            (
                folder / "init.m4s",
                folder / "chunk-stream0-00001.m4s",
                folder / "chunk-stream1-00001.m4s",
            ),
        )

    def test_reports_recordings_it_cannot_load(self):
        cases = {
            "session.mpd": "session.mpd was not found",
            "init-stream0.m4s": "no initialization chunk init-stream0.m4s",
            "chunk-stream0-00001.m4s": "no media segments",
        }
        for name, message in cases.items():
            with self.subTest(message=message):
                write_recording(self.folder, {"0": [1]})
                (self.folder / name).unlink()
                with self.assertRaisesRegex(ExportError, message):
                    load_recording(self.folder)

        write_recording(self.folder, {"0": [1]}, initialization="../init-$RepresentationID$.m4s")
        with self.assertRaisesRegex(ExportError, "outside the recording folder"):
            load_recording(self.folder)

    def test_unreadable_folder_stops_the_load(self):
        write_recording(self.folder, {"0": [1]})
        with (
            patch("os.scandir", side_effect=PermissionError("denied")),
            self.assertRaises(PermissionError),
        ):
            load_recording(self.folder)


if __name__ == "__main__":
    unittest.main()
