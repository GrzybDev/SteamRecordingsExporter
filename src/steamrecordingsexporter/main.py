from pathlib import Path
from typing import Annotated

import typer
from ffmpeg import FFmpeg
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    track,
)

from steamrecordingsexporter.helpers import get_filename
from steamrecordingsexporter.mpd import MPD

app = typer.Typer()


@app.command(
    help="Export a Steam recording clip from the specified input directory to a single video file."
)
def main(
    input_dir: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            help="Clip folder with media files you want to export (this is the folder with m4s files inside).",
        ),
    ],
    output_file: Annotated[
        Path | None,
        typer.Argument(
            writable=True,
            help="Output file path or directory where the exported media will be saved.",
        ),
    ] = None,
    compact: Annotated[
        bool,
        typer.Option(
            "--compact",
            "-c",
            help="Remove processed chunks immediately to save up on disk space",
        ),
    ] = False,
):
    if output_file is not None and output_file.is_dir():
        output_file = output_file / f"{input_dir.name}.mp4"

    # Verify whether "session.mpd" exists in the input directory
    session_file = input_dir / "session.mpd"

    if not session_file.exists():
        typer.echo(
            f"Error: 'session.mpd' not found in the input directory: {input_dir}"
        )

        raise typer.Exit(code=1)

    __mpd = MPD(session_file.read_text())
    representations = __mpd.get_representations()
    representations_segments_count = {}

    for rep in representations:
        # Basic validation of the representation data
        if rep["id"] is None or rep["initialization"] is None or rep["media"] is None:
            typer.echo(f"Warning: Skipping representation with missing data: {rep}")
            continue

        init_chunk_filename = get_filename(
            rep["initialization"], RepresentationID=rep["id"]
        )

        if not (input_dir / init_chunk_filename).exists():
            typer.echo(
                f"Error: Initialization chunk '{init_chunk_filename}' not found for representation ID '{rep['id']}'. Cannot continue.",
                err=True,
            )
            raise typer.Exit(code=1)

        segment_filename_template = get_filename(
            rep["media"], RepresentationID=rep["id"], Number="*"
        )

        segment_files = list(input_dir.glob(segment_filename_template))
        representations_segments_count[rep["id"]] = len(segment_files)

    stream_filename_template = "stream-$RepresentationID$.m4s"

    for rep_id, segments_count in representations_segments_count.items():
        stream_file = input_dir / get_filename(
            stream_filename_template, RepresentationID=rep_id
        )

        with open(stream_file, "wb") as output_stream:
            for value in track(
                range(segments_count + 1),
                description=f"Joining segments for media stream with ID: {rep_id}",
            ):
                if value == 0:
                    chunk_filename = get_filename(
                        rep["initialization"],  # type: ignore
                        RepresentationID=rep_id,
                    )
                else:
                    chunk_filename = get_filename(
                        rep["media"],  # type: ignore
                        RepresentationID=rep_id,
                        Number=value,
                    )

                chunk_path = input_dir / chunk_filename

                if not chunk_path.exists():
                    typer.echo(
                        f"Warning: Expected chunk file '{chunk_filename}' not found for representation ID '{rep_id}'. Skipping remaining segments."
                    )
                    break

                output_stream.write(chunk_path.read_bytes())
                output_stream.flush()

                if compact:
                    chunk_path.unlink()

    with Progress(
        SpinnerColumn(finished_text="\u2713"),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
    ) as progress:
        task = progress.add_task(
            description="Merging streams into final output file...", total=1
        )

        # Now, merge the streams using FFmpeg
        ffmpeg = (
            FFmpeg()
            .option("y")
            .output(
                str(output_file) if output_file else f"{input_dir.name}.mp4",
                {"codec": "copy"},
            )
        )

        for rep_id in representations_segments_count.keys():
            stream_file = input_dir / get_filename(
                stream_filename_template, RepresentationID=rep_id
            )
            ffmpeg = ffmpeg.input(str(stream_file))

        ffmpeg.execute()
        progress.update(
            task,
            description="Video exported successfully! (Saved as: {})".format(
                output_file if output_file else f"{input_dir.name}.mp4"
            ),
            advance=1,
        )

    # Cleanup stream files
    for rep_id in representations_segments_count.keys():
        stream_file = input_dir / get_filename(
            stream_filename_template, RepresentationID=rep_id
        )

        if stream_file.exists():
            stream_file.unlink()


if __name__ == "__main__":
    app()
