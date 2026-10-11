import shutil
from collections.abc import Iterable, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated

import typer
from ffmpeg import FFmpeg
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeElapsedColumn

from steamrecordingsexporter.errors import ExportError
from steamrecordingsexporter.recording import Recording, Stream, load_recording

app = typer.Typer()


@app.command(help="Export a Steam recording to a single video file.")
def main(
    input_dir: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            readable=True,
            help="Recording folder holding session.mpd and the chunks it lists.",
        ),
    ],
    output_file: Annotated[
        Path | None,
        typer.Argument(
            writable=True,
            help="Output file, or the folder to save it in as <recording folder name>.mp4.",
        ),
    ] = None,
    compact: Annotated[
        bool,
        typer.Option(
            "--compact", "-c", help="Remove processed chunks immediately to save up on disk space"
        ),
    ] = False,
) -> None:
    try:
        recording = load_recording(input_dir)
        output = _output_path(output_file, recording)
        warnings = [_gap_warning(stream) for stream in recording.streams if stream.missing]
        for warning in warnings:
            _warn(warning)
        with Progress(
            TextColumn("{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
        ) as progress:
            export(recording, output, progress, compact)
    except (ExportError, OSError) as error:
        typer.echo(f"Error: {error}")
        raise typer.Exit(1) from error
    count = len(warnings)
    summary = f" with {count} warning{'' if count == 1 else 's'}" if count else ""
    typer.echo(f"Exported{summary}: {output}")


def _output_path(output: Path | None, recording: Recording) -> Path:
    output = (output or Path.cwd()).resolve()
    if output.is_dir():
        return output / f"{recording.folder.name}.mp4"
    return output


def _gap_warning(stream: Stream) -> str:
    total = len(stream.segments) + len(stream.missing)
    return (
        f"Stream {stream.id!r} is missing {len(stream.missing)} of {total} segments "
        f"({_ranges(stream.missing)}), so the video will have gaps"
    )


def _ranges(numbers: Sequence[int]) -> str:
    spans: list[list[int]] = []
    for number in numbers:
        if spans and spans[-1][1] == number - 1:
            spans[-1][1] = number
        else:
            spans.append([number, number])
    return ", ".join(str(first) if first == last else f"{first}-{last}" for first, last in spans)


def _warn(message: str) -> None:
    typer.echo(f"Warning: {message}")


def export(
    recording: Recording, output: Path, progress: Progress | None = None, compact: bool = False
) -> None:
    """Join the chunks of each stream and merge the streams into output without re-encoding."""
    progress = progress or Progress(disable=True)
    with TemporaryDirectory(prefix="steamrecordingsexporter-") as scratch:
        joined = []
        for index, stream in enumerate(recording.streams):
            target = Path(scratch, f"stream-{index}.m4s")
            _join(
                progress.track(stream.chunks, description=f"Joining stream {stream.id}"),
                target,
                compact,
            )
            joined.append(target)
        task = progress.add_task("Merging the streams", total=None)
        _merge(joined, output)
        progress.update(task, total=1, completed=1)


def _join(chunks: Iterable[Path], target: Path, compact: bool) -> None:
    with target.open("wb") as joined:
        for chunk in chunks:
            with chunk.open("rb") as source:
                shutil.copyfileobj(source, joined)
            if compact:
                chunk.unlink()


def _merge(streams: Sequence[Path], output: Path) -> None:
    # Written beside the output and moved over it only once complete, so a failed export keeps
    # the previous file.
    partial = output.with_name(f".{output.stem}.partial{output.suffix}")
    command = FFmpeg().option("y").option("nostdin")
    # Each stream keeps its own timestamps, so one that lost its first segments stays in sync.
    command.option("copyts")
    for stream in streams:
        command.input(stream)
    command.output(
        partial,
        codec="copy",
        avoid_negative_ts="make_zero",
    )
    try:
        command.execute()
        if partial.stat().st_size == 0:
            raise ExportError("FFmpeg wrote an empty file")
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
