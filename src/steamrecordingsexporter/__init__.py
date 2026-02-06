from pathlib import Path
from typing import Annotated

import typer

from steamrecordingsexporter.exporter import Exporter

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

    exporter = Exporter(input_dir, output_file, compact)
    representations = exporter.get_session_data(session_file)
    exporter.join_segments(representations)

    streams_to_export = [rep.id for rep in representations]
    exporter.export(streams_to_export)
    exporter.cleanup(streams_to_export)
