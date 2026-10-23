import shutil
import subprocess
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory

from steamrecordingsexporter import messages
from steamrecordingsexporter.errors import ExportError
from steamrecordingsexporter.recording import Recording, Stream


class ExportProgress:
    """Receives how far an export has got; each method does nothing unless overridden."""

    def joined(self, stream: Stream, chunks: int) -> None:
        """Report how many chunks of a stream are joined so far.

        Args:
            stream: The stream being joined.
            chunks: How many of its chunks are joined.
        """

    def merging(self) -> None:
        """Report that the merge of the joined streams has started."""

    def merged(self) -> None:
        """Report that the merge has finished."""


_SILENT = ExportProgress()


def export(recording: Recording, output: Path, progress: ExportProgress = _SILENT) -> None:
    """Join the chunks of each stream and merge the streams into output without re-encoding.

    Args:
        recording: The recording to export.
        output: The file to write.
        progress: Receives how far the export has got.

    Raises:
        ExportError: If FFmpeg is missing, the output is unsafe or the merge fails.
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise ExportError(messages.FFMPEG_MISSING)
    _check_output(recording, output)
    # Beside the output, on the drive that has to hold the export anyway, since the joined
    # streams are as large as the recording.
    with TemporaryDirectory(prefix=".steamrecordingsexporter-", dir=output.parent) as scratch:
        joined = []
        for index, stream in enumerate(recording.streams):
            target = Path(scratch, f"stream-{index}.m4s")
            _join(stream, target, progress)
            joined.append(target)
        progress.merging()
        _merge(ffmpeg, joined, output)
        progress.merged()


def remove_chunks(recording: Recording) -> dict[Path, OSError]:
    """Delete the chunks of the recording and the folders they leave empty.

    Returns the chunks that could not be deleted, since the export is complete by then.

    Args:
        recording: The exported recording.
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
    """Refuse an output whose folder is missing or that is a file of the recording."""
    if not output.parent.is_dir():
        raise ExportError(messages.OUTPUT_FOLDER_MISSING.format(folder=output.parent))
    if output.exists() and any(
        output.samefile(source) for source in (recording.manifest, *recording.chunks)
    ):
        raise ExportError(messages.OUTPUT_IN_RECORDING.format(output=output))


def _join(stream: Stream, target: Path, progress: ExportProgress) -> None:
    with target.open("wb") as joined:
        for count, chunk in enumerate(stream.chunks, start=1):
            with chunk.open("rb") as source:
                shutil.copyfileobj(source, joined)
            progress.joined(stream, count)


def _merge(ffmpeg: str, streams: Sequence[Path], output: Path) -> None:
    # Written beside the output and moved over it only once complete, so a failed export keeps
    # the previous file.
    partial = output.with_name(f".{output.stem}.partial{output.suffix}")
    # Each stream keeps its own timestamps, so one that lost its first segments stays in sync.
    arguments = [ffmpeg, "-y", "-nostdin", "-copyts"]
    for stream in streams:
        arguments += ["-i", str(stream)]
    arguments += ["-codec", "copy"]
    for index in range(len(streams)):
        arguments += ["-map", str(index)]
    arguments += ["-avoid_negative_ts", "make_zero", str(partial)]
    try:
        subprocess.run(
            arguments, check=True, capture_output=True, encoding="utf-8", errors="replace"
        )
        if partial.stat().st_size == 0:
            raise ExportError(messages.EMPTY_OUTPUT)
        partial.replace(output)
    except subprocess.CalledProcessError as error:
        # FFmpeg ends its log with the reason it stopped.
        reason = next(reversed(error.stderr.strip().splitlines()), "")
        raise ExportError(messages.MERGE_FAILED.format(reason=reason)) from error
    finally:
        partial.unlink(missing_ok=True)
