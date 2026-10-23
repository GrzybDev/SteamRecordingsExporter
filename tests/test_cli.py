from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from steamrecordingsexporter.cli import app
from support import FakeFFmpeg, contents, write_recording


def run_cli(*arguments: Path | str) -> Result:
    """Run the command line with the arguments and return what it printed.

    Args:
        arguments: The command-line arguments.
    """
    return CliRunner().invoke(app, [str(argument) for argument in arguments])


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """Write a five-segment recording whose streams lost segments inside and at the end."""
    return write_recording(
        tmp_path / "clip",
        {"0": [1, 3], "1": [1, 2, 4, 5]},
        duration="PT15S",
        segment_duration=3,
    )


def test_exports_and_counts_the_warnings(tmp_path: Path, folder: Path, ffmpeg: FakeFFmpeg) -> None:
    result = run_cli(folder, tmp_path)
    assert result.exit_code == 0, result.output
    assert (
        "Warning: Stream '0' is missing 3 of 5 segments (2, 4-5), which the export leaves out"
        in result.output
    )
    assert (
        "Warning: Stream '1' is missing 1 of 5 segments (3), which the export leaves out"
        in result.output
    )
    assert f"Exported with 2 warnings: {tmp_path / 'clip.mp4'}" in result.output
    assert (tmp_path / "clip.mp4").read_bytes() == b"MP4"


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (None, "clip.mp4"),
        ("videos", "videos/clip.mp4"),
        ("named", "named.mp4"),
        ("named.mkv", "named.mkv"),
    ],
)
def test_names_the_output_after_the_recording_unless_given_a_file(
    tmp_path: Path,
    folder: Path,
    ffmpeg: FakeFFmpeg,
    monkeypatch: pytest.MonkeyPatch,
    given: str | None,
    expected: str,
) -> None:
    (tmp_path / "videos").mkdir()
    monkeypatch.chdir(tmp_path)
    result = run_cli(folder, *([tmp_path / given] if given else []))
    assert result.exit_code == 0, result.output
    assert (tmp_path / expected).is_file(), result.output


def test_compact_deletes_the_chunks_and_warns_about_any_left(
    tmp_path: Path, folder: Path, ffmpeg: FakeFFmpeg, monkeypatch: pytest.MonkeyPatch
) -> None:
    locked = folder / "chunk-stream1-00005.m4s"
    unlink = Path.unlink

    def unlink_unless_locked(path: Path, missing_ok: bool = False) -> None:
        if path == locked:
            raise PermissionError("locked")
        unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink_unless_locked)
    result = run_cli(folder, tmp_path, "--compact")
    assert result.exit_code == 0, result.output
    assert "Warning: Could not delete 1 of 8 chunks: locked" in result.output
    assert "Exported with 3 warnings" in result.output
    assert sorted(contents(folder)) == ["chunk-stream1-00005.m4s", "session.mpd"]


def test_reports_errors_with_a_failing_exit_code(tmp_path: Path) -> None:
    result = run_cli(tmp_path)
    assert result.exit_code == 1, result.output
    assert "Error: session.mpd was not found" in result.output
    assert "Exported" not in result.output
