import json
import math
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from ffmpeg import FFmpegError

from steamrecordingsexporter.exporter import Exporter


FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and ffprobe must be available on PATH")
class ExportIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.fixture_directory.cleanup)
        root = Path(cls.fixture_directory.name)
        cls.fixture = root / "recording"
        cls.fixture.mkdir()

        # Raw RGB frames and WAV files avoid depending on optional lavfi devices.
        duration = 2
        sample_rate = 8000
        for index, frequency in enumerate((440, 880), start=1):
            with wave.open(str(root / f"audio-{index}.wav"), "wb") as audio:
                audio.setparams((1, 2, sample_rate, 0, "NONE", "not compressed"))
                audio.writeframes(
                    b"".join(
                        struct.pack("<h", int(6000 * math.sin(2 * math.pi * frequency * sample / sample_rate)))
                        for sample in range(duration * sample_rate)
                    )
                )

        command = [
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "32x32", "-r", "10", "-i", "pipe:0",
            "-i", str(root / "audio-1.wav"), "-i", str(root / "audio-2.wav"),
            "-map", "0:v:0", "-map", "1:a:0", "-map", "2:a:0",
            "-c:v", "mpeg4", "-pix_fmt", "yuv420p", "-g", "10", "-c:a", "aac", "-b:a", "32k",
            "-use_template", "1", "-use_timeline", "0", "-seg_duration", "1",
            "-init_seg_name", "init-$RepresentationID$.m4s",
            "-media_seg_name", "chunk-$RepresentationID$-$Number%05d$.m4s",
            "-f", "dash", "session.mpd",
        ]
        frames = b"".join(
            bytes((frame * 10, 40, 180)) * (32 * 32)
            for frame in range(duration * 10)
        )
        generated = subprocess.run(command, input=frames, cwd=cls.fixture, capture_output=True, timeout=30)
        if generated.returncode:
            raise RuntimeError(f"Could not create DASH fixture: {generated.stderr.decode(errors='replace')}")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.clip = self.root / "recording"
        shutil.copytree(self.fixture, self.clip)
        self.output = self.root / "recording.mp4"

    def snapshot_sources(self):
        return {path.relative_to(self.clip): path.read_bytes() for path in self.clip.rglob("*") if path.is_file()}

    def assert_exported_streams(self):
        probed = subprocess.run(
            [FFPROBE, "-v", "error", "-count_packets", "-show_streams", "-of", "json", str(self.output)],
            capture_output=True, check=True, timeout=30,
        )
        streams = json.loads(probed.stdout)["streams"]
        self.assertEqual(Counter(stream["codec_type"] for stream in streams), {"video": 1, "audio": 2})
        self.assertEqual(Counter(stream["codec_name"] for stream in streams), {"mpeg4": 1, "aac": 2})
        self.assertTrue(all(int(stream["nb_read_packets"]) >= 8 for stream in streams))
        self.assertTrue(all(1.5 <= float(stream["duration"]) <= 2.5 for stream in streams))

    def test_export_preserves_both_audio_tracks_and_source_chunks(self):
        sources = self.snapshot_sources()
        self.assertEqual(Exporter(self.clip, self.output).run(), self.output)
        self.assert_exported_streams()
        self.assertEqual(self.snapshot_sources(), sources)
        self.assertEqual(list(self.root.glob(".steam-export-*")), [])

    def test_compact_removes_chunks_after_the_complete_output_exists(self):
        sources = self.snapshot_sources()
        exporter = Exporter(self.clip, self.output, compact=True)
        cleanup = exporter.cleanup

        def verify_output_then_cleanup(paths):
            self.assert_exported_streams()
            self.assertEqual(self.snapshot_sources(), sources)
            cleanup(paths)

        with patch.object(exporter, "cleanup", side_effect=verify_output_then_cleanup) as cleanup_spy:
            self.assertEqual(exporter.run(), self.output)
            cleanup_spy.assert_called_once()
        self.assertEqual(self.snapshot_sources(), {Path("session.mpd"): sources[Path("session.mpd")]})

    def test_ffmpeg_failure_preserves_sources_and_existing_output_in_compact_mode(self):
        # Valid metadata with corrupt media reaches the real FFmpeg failure path.
        (self.clip / "init-0.m4s").write_bytes(b"This is not an MP4 initialization segment.")
        sources = self.snapshot_sources()
        existing_output = b"Previously exported recording"
        self.output.write_bytes(existing_output)

        with self.assertRaises(FFmpegError):
            Exporter(self.clip, self.output, compact=True).run()
        self.assertEqual(self.snapshot_sources(), sources)
        self.assertEqual(self.output.read_bytes(), existing_output)
        self.assertEqual(list(self.root.glob(".steam-export-*")), [])

    def test_missing_first_segment_preserves_relative_stream_timestamps(self):
        def first_packet_pts(path):
            probed = subprocess.run(
                [FFPROBE, "-v", "error", "-show_packets", "-show_entries", "packet=stream_index,pts_time", "-of", "json", str(path)],
                capture_output=True, check=True, timeout=30,
            )
            first_pts = {}
            for packet in json.loads(probed.stdout)["packets"]:
                first_pts.setdefault(packet["stream_index"], float(packet["pts_time"]))
            return first_pts

        for missing_representations in ((0,), (1,), (0, 1, 2)):
            with self.subTest(missing_representations=missing_representations):
                scenario = "-".join(map(str, missing_representations))
                clip = self.root / f"missing-{scenario}"
                shutil.copytree(self.fixture, clip)
                for representation in missing_representations:
                    (clip / f"chunk-{representation}-00001.m4s").unlink()
                joined = self.root / f"joined-{scenario}"
                joined.mkdir()
                output = self.root / f"missing-{scenario}.mp4"
                exporter = Exporter(clip, output)
                streams = exporter.join_segments(exporter.get_session_data(clip / "session.mpd"), joined)
                source_pts = [first_packet_pts(stream)[0] for stream in streams]

                exporter.run()
                output_pts = first_packet_pts(output)
                for index in range(1, len(streams)):
                    self.assertAlmostEqual(
                        output_pts[index] - output_pts[0], source_pts[index] - source_pts[0], delta=0.02,
                    )
                self.assertAlmostEqual(min(output_pts.values()), 0, delta=0.02)


if __name__ == "__main__":
    unittest.main()
