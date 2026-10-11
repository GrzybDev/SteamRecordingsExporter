import shutil
from collections.abc import Iterable, Sequence
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory

from ffmpeg import FFmpeg, FFmpegError
from rich.progress import Progress

from steamrecordingsexporter.errors import ExportError
from steamrecordingsexporter.recording import Recording


def export(recording: Recording, output: Path, progress: Progress | None = None) -> None:
    """Join the chunks of each stream and merge the streams into output without re-encoding."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise ExportError("FFmpeg was not found on PATH; install it before exporting")
    _check_output(recording, output)
    progress = progress or Progress(disable=True)
    with TemporaryDirectory(prefix="steamrecordingsexporter-") as scratch:
        joined = []
        for index, stream in enumerate(recording.streams):
            target = Path(scratch, f"stream-{index}.m4s")
            _join(progress.track(stream.chunks, description=f"Joining stream {stream.id}"), target)
            joined.append(target)
        task = progress.add_task("Merging the streams", total=None)
        _merge(ffmpeg, joined, output)
        progress.update(task, total=1, completed=1)


def remove_chunks(recording: Recording) -> dict[Path, OSError]:
    """Delete the chunks of the recording and the folders they leave empty.

    Returns the chunks that could not be deleted, since the export is complete by then.
    """
    failures = {}
    for chunk in recording.chunks:
        try:
            chunk.unlink(missing_ok=True)
        except OSError as error:
            failures[chunk] = error
    folders = {
        parent
        for chunk in recording.chunks
        for parent in chunk.parents
        if parent != recording.folder and parent.is_relative_to(recording.folder)
    }
    for folder in sorted(folders, key=lambda folder: len(folder.parts), reverse=True):
        with suppress(OSError):
            folder.rmdir()
    return failures


def _check_output(recording: Recording, output: Path) -> None:
    if not output.parent.is_dir():
        raise ExportError(f"The output folder does not exist: {output.parent}")
    if output.exists() and any(
        output.samefile(source) for source in (recording.manifest, *recording.chunks)
    ):
        raise ExportError(f"The output would overwrite a file of the recording: {output}")


def _join(chunks: Iterable[Path], target: Path) -> None:
    with target.open("wb") as joined:
        for chunk in chunks:
            with chunk.open("rb") as source:
                shutil.copyfileobj(source, joined)


def _merge(ffmpeg: str, streams: Sequence[Path], output: Path) -> None:
    # Written beside the output and moved over it only once complete, so a failed export keeps
    # the previous file.
    partial = output.with_name(f".{output.stem}.partial{output.suffix}")
    command = FFmpeg(ffmpeg).option("y").option("nostdin")
    # Each stream keeps its own timestamps, so one that lost its first segments stays in sync.
    command.option("copyts")
    for stream in streams:
        command.input(stream)
    command.output(
        partial,
        codec="copy",
        map=[str(index) for index in range(len(streams))],
        avoid_negative_ts="make_zero",
    )
    try:
        command.execute()
        if partial.stat().st_size == 0:
            raise ExportError("FFmpeg wrote an empty file")
        partial.replace(output)
    except FFmpegError as error:
        raise ExportError(f"FFmpeg could not merge the streams: {error.message}") from error
    finally:
        partial.unlink(missing_ok=True)
