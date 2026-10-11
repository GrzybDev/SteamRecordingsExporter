from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeElapsedColumn

from steamrecordingsexporter.errors import ExportError
from steamrecordingsexporter.export import export, remove_chunks
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
            "--compact", "-c", help="Delete the recording's chunks once the export succeeds."
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
            console=Console(stderr=True),
        ) as progress:
            export(recording, output, progress)
        if compact and (failures := remove_chunks(recording)):
            warnings.append(_removal_warning(failures, recording))
            _warn(warnings[-1])
    except (ExportError, OSError) as error:
        typer.secho(f"Error: {error}", fg="red", err=True)
        raise typer.Exit(1) from error
    count = len(warnings)
    summary = f" with {count} warning{'' if count == 1 else 's'}" if count else ""
    typer.echo(f"Exported{summary}: {output}")


def _output_path(output: Path | None, recording: Recording) -> Path:
    output = (output or Path.cwd()).resolve()
    if output.is_dir():
        return output / f"{recording.folder.name}.mp4"
    # FFmpeg picks the container from the extension.
    return output if output.suffix else output.with_name(f"{output.name}.mp4")


def _gap_warning(stream: Stream) -> str:
    total = len(stream.segments) + len(stream.missing)
    return (
        f"Stream {stream.id!r} is missing {len(stream.missing)} of {total} segments "
        f"({_ranges(stream.missing)}), so the video will have gaps"
    )


def _removal_warning(failures: dict[Path, OSError], recording: Recording) -> str:
    first = next(iter(failures.values()))
    return f"Could not delete {len(failures)} of {len(recording.chunks)} chunks: {first}"


def _ranges(numbers: Sequence[int]) -> str:
    spans: list[list[int]] = []
    for number in numbers:
        if spans and spans[-1][1] == number - 1:
            spans[-1][1] = number
        else:
            spans.append([number, number])
    return ", ".join(str(first) if first == last else f"{first}-{last}" for first, last in spans)


def _warn(message: str) -> None:
    typer.secho(f"Warning: {message}", fg="yellow", err=True)
