import os
import shutil
from pathlib import Path

import pytest

from steamrecordingsexporter.errors import ExportError
from steamrecordingsexporter.export import ExportProgress, export, remove_chunks
from steamrecordingsexporter.recording import Stream, load_recording
from support import FakeFFmpeg, contents, write_recording


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """Write a recording of two streams with two segments each."""
    return write_recording(tmp_path / "clip", {"0": [1, 2], "1": [1, 2]})


def test_merges_the_joined_streams_into_the_output(
    tmp_path: Path, folder: Path, ffmpeg: FakeFFmpeg
) -> None:
    before = contents(folder)
    export(load_recording(folder), tmp_path / "clip.mp4")
    [run] = ffmpeg.runs
    assert run.input_contents == [
        f"init-stream{rep_id}.m4s;chunk-stream{rep_id}-00001.m4s;"
        f"chunk-stream{rep_id}-00002.m4s;".encode()
        for rep_id in ("0", "1")
    ]
    assert (tmp_path / "clip.mp4").read_bytes() == b"MP4"
    assert contents(folder) == before
    assert sorted(path.name for path in tmp_path.iterdir()) == ["clip", "clip.mp4"]


def test_reports_the_progress_of_each_stream_and_the_merge(
    tmp_path: Path, folder: Path, ffmpeg: FakeFFmpeg
) -> None:
    events: list[tuple[str, int]] = []

    class Recorder(ExportProgress):
        def joined(self, stream: Stream, chunks: int) -> None:
            events.append((stream.id, chunks))

        def merging(self) -> None:
            events.append(("merging", len(ffmpeg.runs)))

        def merged(self) -> None:
            events.append(("merged", len(ffmpeg.runs)))

    export(load_recording(folder), tmp_path / "clip.mp4", Recorder())
    assert events == [
        *((rep_id, chunks) for rep_id in ("0", "1") for chunks in (1, 2, 3)),
        ("merging", 0),
        ("merged", 1),
    ]


@pytest.mark.parametrize(
    ("written", "returncode", "stderr", "message"),
    [
        (b"MP4", 1, "Opening input\nInvalid data\n", "could not merge the streams: Invalid data$"),
        (b"", 0, "", "empty file"),
    ],
)
def test_failed_merge_keeps_the_previous_output_and_the_recording(
    tmp_path: Path,
    folder: Path,
    ffmpeg: FakeFFmpeg,
    written: bytes,
    returncode: int,
    stderr: str,
    message: str,
) -> None:
    ffmpeg.output, ffmpeg.returncode, ffmpeg.stderr = written, returncode, stderr
    output = tmp_path / "clip.mp4"
    output.write_bytes(b"EARLIER")
    before = contents(folder)
    with pytest.raises(ExportError, match=message):
        export(load_recording(folder), output)
    assert output.read_bytes() == b"EARLIER"
    assert contents(folder) == before
    assert sorted(path.name for path in tmp_path.iterdir()) == ["clip", "clip.mp4"]


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("clip/session.mpd", "overwrite a file of the recording"),
        ("clip/init-stream1.m4s", "overwrite a file of the recording"),
        ("hardlink.mp4", "overwrite a file of the recording"),
        ("missing/clip.mp4", "output folder does not exist"),
    ],
)
def test_refuses_outputs_that_would_overwrite_the_recording(
    tmp_path: Path, folder: Path, ffmpeg: FakeFFmpeg, name: str, message: str
) -> None:
    os.link(folder / "chunk-stream0-00001.m4s", tmp_path / "hardlink.mp4")
    before = contents(folder)
    with pytest.raises(ExportError, match=message):
        export(load_recording(folder), tmp_path / name)
    assert ffmpeg.runs == []
    assert contents(folder) == before


def test_needs_ffmpeg_on_path(
    tmp_path: Path, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ExportError, match="FFmpeg was not found"):
        export(load_recording(folder), tmp_path / "clip.mp4")


def test_removes_only_the_chunks_and_the_folders_they_leave_empty(tmp_path: Path) -> None:
    folder = write_recording(
        tmp_path / "nested",
        {"0": [1, 2], "1": [1]},
        media="media/$RepresentationID$/$Number$.m4s",
    )
    (folder / "media" / "1" / "notes.txt").write_text("keep")
    (folder / "thumbnail.jpg").write_text("keep")
    assert remove_chunks(load_recording(folder)) == {}
    assert sorted(contents(folder)) == ["media/1/notes.txt", "session.mpd", "thumbnail.jpg"]
    assert not (folder / "media" / "0").exists()
