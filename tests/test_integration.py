import json
import math
import shutil
import struct
import subprocess
import wave
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from steamrecordingsexporter.cli import app
from steamrecordingsexporter.export import export
from steamrecordingsexporter.recording import load_recording
from support import contents

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

pytestmark = pytest.mark.skipif(
    not (FFMPEG and FFPROBE), reason="FFmpeg and ffprobe must be available on PATH"
)


def probe(path: Path, *arguments: str) -> Any:
    """Return what ffprobe reports about the file as parsed JSON.

    Args:
        path: The media file to probe.
        arguments: The ffprobe options that select what to report.
    """
    assert FFPROBE
    result = subprocess.run(
        [FFPROBE, "-v", "error", *arguments, "-of", "json", str(path)],
        capture_output=True,
        check=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def first_packet_times(path: Path) -> dict[int, float]:
    """Return the presentation time of the first packet of each stream in the file.

    Args:
        path: The media file to probe.
    """
    packets = probe(path, "-show_packets", "-show_entries", "packet=stream_index,pts_time")
    times: dict[int, float] = {}
    for packet in packets["packets"]:
        times.setdefault(packet["stream_index"], float(packet["pts_time"]))
    return times


def assert_exported_streams(output: Path) -> None:
    """Check that the file holds the video and both audio tracks of the whole recording.

    Args:
        output: The exported file.
    """
    streams = probe(output, "-count_packets", "-show_streams")["streams"]
    assert Counter(stream["codec_name"] for stream in streams) == {"mpeg4": 1, "aac": 2}
    for stream in streams:
        assert int(stream["nb_read_packets"]) >= 8
        assert float(stream["duration"]) == pytest.approx(2, abs=0.5)


@pytest.fixture(scope="module")
def fixture(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Record two seconds of video and two audio tracks as DASH chunks named like Steam's."""
    # One-second chunks, against Steam's three, keep the recording small.
    assert FFMPEG
    root = tmp_path_factory.mktemp("source")
    folder = root / "recording"
    folder.mkdir()
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
    command: list[str | Path] = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y"]
    command += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "32x32", "-r", "10"]
    command += ["-i", "pipe:0", "-i", root / "audio-1.wav", "-i", root / "audio-2.wav"]
    command += ["-map", "0:v:0", "-map", "1:a:0", "-map", "2:a:0"]
    command += ["-c:v", "mpeg4", "-pix_fmt", "yuv420p", "-g", "10"]
    command += ["-c:a", "aac", "-b:a", "32k"]
    command += ["-use_template", "1", "-use_timeline", "0", "-seg_duration", "1"]
    command += ["-init_seg_name", "init-stream$RepresentationID$.m4s"]
    command += ["-media_seg_name", "chunk-stream$RepresentationID$-$Number%05d$.m4s"]
    command += ["-f", "dash", "session.mpd"]
    subprocess.run(command, input=frames, cwd=folder, check=True, timeout=30)
    return folder


@pytest.fixture
def clip(tmp_path: Path, fixture: Path) -> Path:
    """Copy the generated recording into the test's own folder."""
    return Path(shutil.copytree(fixture, tmp_path / "recording"))


def test_exports_the_video_and_both_audio_tracks(tmp_path: Path, clip: Path) -> None:
    files = contents(clip)
    export(load_recording(clip), tmp_path / "recording.mp4")
    assert_exported_streams(tmp_path / "recording.mp4")
    assert contents(clip) == files
    assert sorted(path.name for path in tmp_path.iterdir()) == ["recording", "recording.mp4"]


def test_compact_leaves_only_the_manifest_beside_a_complete_export(
    tmp_path: Path, clip: Path
) -> None:
    manifest = (clip / "session.mpd").read_bytes()
    output = tmp_path / "recording.mp4"
    result = CliRunner().invoke(app, [str(clip), str(output), "--compact"])
    assert result.exit_code == 0, result.output
    assert_exported_streams(output)
    assert contents(clip) == {"session.mpd": manifest}


def test_ffmpeg_failure_keeps_the_recording_and_the_previous_export(
    tmp_path: Path, clip: Path
) -> None:
    (clip / "init-stream0.m4s").write_bytes(b"Not an MP4 initialization segment")
    files = contents(clip)
    output = tmp_path / "recording.mp4"
    output.write_bytes(b"Previous export")
    result = CliRunner().invoke(app, [str(clip), str(output), "--compact"])
    assert result.exit_code == 1, result.output
    assert "FFmpeg could not merge the streams" in result.output
    assert contents(clip) == files
    assert output.read_bytes() == b"Previous export"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["recording", "recording.mp4"]


@pytest.mark.parametrize("offset", ["0.5", "-0.25"])
def test_audio_offset_moves_both_audio_tracks_against_the_video(
    tmp_path: Path, clip: Path, offset: str
) -> None:
    export(load_recording(clip), tmp_path / "plain.mp4")
    plain = first_packet_times(tmp_path / "plain.mp4")
    output = tmp_path / "shifted.mp4"
    result = CliRunner().invoke(app, [str(clip), str(output), "--audio-offset", offset])
    assert result.exit_code == 0, result.output
    assert_exported_streams(output)
    shifted = first_packet_times(output)
    for audio in (1, 2):
        assert shifted[audio] - shifted[0] == pytest.approx(
            plain[audio] - plain[0] + float(offset), abs=0.02
        )


@pytest.mark.parametrize("lost", [("0",), ("1",), ("0", "1", "2")])
def test_streams_that_lost_their_first_segment_stay_in_sync(
    tmp_path: Path, clip: Path, lost: tuple[str, ...]
) -> None:
    for rep_id in lost:
        (clip / f"chunk-stream{rep_id}-00001.m4s").unlink()
    recording = load_recording(clip)
    starts = []
    for stream in recording.streams:
        joined = tmp_path / f"{stream.id}.m4s"
        joined.write_bytes(b"".join(chunk.read_bytes() for chunk in stream.chunks))
        starts.append(first_packet_times(joined)[0])

    export(recording, tmp_path / "recording.mp4")
    exported = first_packet_times(tmp_path / "recording.mp4")
    for index in range(1, len(starts)):
        assert exported[index] - exported[0] == pytest.approx(starts[index] - starts[0], abs=0.02)
    assert min(exported.values()) == pytest.approx(0, abs=0.02)
