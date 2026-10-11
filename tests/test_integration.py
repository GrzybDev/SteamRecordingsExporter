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

from typer.testing import CliRunner

from steamrecordingsexporter import app, export
from steamrecordingsexporter.recording import load_recording

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def probe(path: Path, *arguments: str) -> dict:
    result = subprocess.run(
        [FFPROBE, "-v", "error", *arguments, "-of", "json", str(path)],
        capture_output=True,
        check=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def first_packet_times(path: Path) -> dict[int, float]:
    packets = probe(path, "-show_packets", "-show_entries", "packet=stream_index,pts_time")
    times: dict[int, float] = {}
    for packet in packets["packets"]:
        times.setdefault(packet["stream_index"], float(packet["pts_time"]))
    return times


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg and ffprobe must be available on PATH")
class ExportIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Record two seconds of video and two audio tracks in one-second chunks, as Steam does."""
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        root = Path(directory.name)
        cls.fixture = root / "recording"
        cls.fixture.mkdir()

        # Raw inputs, since not every FFmpeg build has the lavfi test sources.
        for index, frequency in enumerate((440, 880), start=1):
            with wave.open(str(root / f"audio-{index}.wav"), "wb") as audio:
                audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                audio.writeframes(
                    b"".join(
                        struct.pack("<h", int(6000 * math.sin(2 * math.pi * frequency * n / 8000)))
                        for n in range(2 * 8000)
                    )
                )
        frames = b"".join(bytes((frame * 10, 40, 180)) * (32 * 32) for frame in range(20))
        command = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y"]
        command += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "32x32", "-r", "10"]
        command += ["-i", "pipe:0", "-i", root / "audio-1.wav", "-i", root / "audio-2.wav"]
        command += ["-map", "0:v:0", "-map", "1:a:0", "-map", "2:a:0"]
        command += ["-c:v", "mpeg4", "-pix_fmt", "yuv420p", "-g", "10"]
        command += ["-c:a", "aac", "-b:a", "32k"]
        command += ["-use_template", "1", "-use_timeline", "0", "-seg_duration", "1"]
        command += ["-init_seg_name", "init-stream$RepresentationID$.m4s"]
        command += ["-media_seg_name", "chunk-stream$RepresentationID$-$Number%05d$.m4s"]
        command += ["-f", "dash", "session.mpd"]
        subprocess.run(command, input=frames, cwd=cls.fixture, check=True, timeout=30)

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.clip = self.root / "recording"
        shutil.copytree(self.fixture, self.clip)
        self.output = self.root / "recording.mp4"

    def recording_files(self, clip=None):
        clip = clip or self.clip
        return {path.relative_to(clip): path.read_bytes() for path in clip.rglob("*")}

    def assert_exported_streams(self, output):
        streams = probe(output, "-count_packets", "-show_streams")["streams"]
        self.assertEqual(
            Counter(stream["codec_name"] for stream in streams), {"mpeg4": 1, "aac": 2}
        )
        for stream in streams:
            self.assertGreaterEqual(int(stream["nb_read_packets"]), 8)
            self.assertAlmostEqual(float(stream["duration"]), 2, delta=0.5)

    def test_exports_the_video_and_both_audio_tracks(self):
        files = self.recording_files()
        export(load_recording(self.clip), self.output)
        self.assert_exported_streams(self.output)
        self.assertEqual(self.recording_files(), files)
        self.assertEqual(
            sorted(path.name for path in self.root.iterdir()), ["recording", "recording.mp4"]
        )

    def test_compact_leaves_only_the_manifest_beside_a_complete_export(self):
        manifest = (self.clip / "session.mpd").read_bytes()
        result = CliRunner().invoke(app, [str(self.clip), str(self.output), "--compact"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assert_exported_streams(self.output)
        self.assertEqual(self.recording_files(), {Path("session.mpd"): manifest})

    def test_ffmpeg_failure_keeps_the_recording_and_the_previous_export(self):
        (self.clip / "init-stream0.m4s").write_bytes(b"Not an MP4 initialization segment")
        files = self.recording_files()
        self.output.write_bytes(b"Previous export")
        result = CliRunner().invoke(app, [str(self.clip), str(self.output), "--compact"])
        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("FFmpeg could not merge the streams", result.output)
        self.assertEqual(self.recording_files(), files)
        self.assertEqual(self.output.read_bytes(), b"Previous export")
        self.assertEqual(
            sorted(path.name for path in self.root.iterdir()), ["recording", "recording.mp4"]
        )

    def test_streams_that_lost_their_first_segment_stay_in_sync(self):
        for lost in (("0",), ("1",), ("0", "1", "2")):
            with self.subTest(lost=lost):
                clip = self.root / f"lost-{'-'.join(lost)}"
                shutil.copytree(self.fixture, clip)
                for rep_id in lost:
                    (clip / f"chunk-stream{rep_id}-00001.m4s").unlink()
                recording = load_recording(clip)
                starts = []
                for stream in recording.streams:
                    joined = self.root / f"{clip.name}-{stream.id}.m4s"
                    joined.write_bytes(b"".join(chunk.read_bytes() for chunk in stream.chunks))
                    starts.append(first_packet_times(joined)[0])
                output = self.root / f"{clip.name}.mp4"

                export(recording, output)
                exported = first_packet_times(output)
                for index in range(1, len(starts)):
                    self.assertAlmostEqual(
                        exported[index] - exported[0], starts[index] - starts[0], delta=0.02
                    )
                self.assertAlmostEqual(min(exported.values()), 0, delta=0.02)


if __name__ == "__main__":
    unittest.main()
