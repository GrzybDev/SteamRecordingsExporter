import os
from pathlib import Path

import pytest

from steamrecordingsexporter.errors import ExportError
from steamrecordingsexporter.recording import load_recording
from support import write_recording


def test_loads_each_stream_with_its_chunks_in_order(tmp_path: Path) -> None:
    folder = write_recording(
        tmp_path / "clip",
        {"0": [2, 1, 3], "audio": [1, 2, 3]},
        media="$RepresentationID$/$Number$.m4s",
    )
    recording = load_recording(tmp_path / "clip")
    assert recording.folder == folder
    assert [stream.id for stream in recording.streams] == ["0", "audio"]
    for stream in recording.streams:
        assert [path.relative_to(folder).as_posix() for path in stream.chunks] == [
            f"init-stream{stream.id}.m4s",
            *(f"{stream.id}/{n}.m4s" for n in (1, 2, 3)),
        ]
        assert stream.missing == ()


def test_counts_the_segments_missing_from_each_stream(tmp_path: Path) -> None:
    folder = write_recording(tmp_path, {"0": [5, 6, 8, 11], "1": [7, 8]}, start_number=5)
    recording = load_recording(folder)
    assert [stream.missing for stream in recording.streams] == [(7, 9, 10), (5, 6)]
    assert len(recording.streams[0].segments) == 4


def test_counts_segments_missing_up_to_the_last_one_the_manifest_declares(tmp_path: Path) -> None:
    folder = write_recording(
        tmp_path,
        {"0": [1, 2, 3], "1": [1, 2, 3, 4, 5], "2": [1, 2, 3, 4, 5, 6]},
        duration="PT14.5S",
        segment_duration=3,
    )
    recording = load_recording(folder)
    assert [stream.missing for stream in recording.streams] == [(4, 5), (), ()]
    assert len(recording.streams[2].segments) == 6


def test_ignores_files_that_are_not_segments_of_the_stream(tmp_path: Path) -> None:
    folder = write_recording(tmp_path, {"0": [1, 2]})
    for name in (
        "chunk-stream0-3.m4s",
        "chunk-stream0-00000.m4s",
        "chunk-stream0-00004.m4s.part",
        "chunk-stream1-00005.m4s",
        "thumbnail.jpg",
    ):
        (folder / name).write_bytes(b"other")
    [stream] = load_recording(folder).streams
    assert [path.name for path in stream.segments] == [
        "chunk-stream0-00001.m4s",
        "chunk-stream0-00002.m4s",
    ]
    assert stream.missing == ()


def test_lists_a_shared_initialization_chunk_once(tmp_path: Path) -> None:
    folder = write_recording(tmp_path, {"0": [1], "1": [1]}, initialization="init.m4s")
    assert load_recording(folder).chunks == (
        folder / "init.m4s",
        folder / "chunk-stream0-00001.m4s",
        folder / "chunk-stream1-00001.m4s",
    )


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("session.mpd", "session.mpd was not found"),
        ("init-stream0.m4s", "no initialization chunk init-stream0.m4s"),
        ("chunk-stream0-00001.m4s", "no media segments"),
    ],
)
def test_reports_recordings_without_their_files(tmp_path: Path, name: str, message: str) -> None:
    folder = write_recording(tmp_path, {"0": [1]})
    (folder / name).unlink()
    with pytest.raises(ExportError, match=message):
        load_recording(folder)


def test_refuses_chunks_outside_the_recording_folder(tmp_path: Path) -> None:
    folder = write_recording(
        tmp_path / "clip", {"0": [1]}, initialization="../init-$RepresentationID$.m4s"
    )
    with pytest.raises(ExportError, match="outside the recording folder"):
        load_recording(folder)


def test_unreadable_folder_stops_the_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = write_recording(tmp_path, {"0": [1]})

    def denied(path: str) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(os, "scandir", denied)
    with pytest.raises(PermissionError):
        load_recording(folder)
