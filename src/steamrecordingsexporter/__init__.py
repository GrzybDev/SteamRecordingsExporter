import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Annotated, Optional

import typer
from ffmpeg import FFmpegError

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
            help="Clip folder containing session.mpd and the media segment files.",
        ),
    ],
    output_file: Annotated[
        Optional[Path],
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
            help="Remove processed chunks after a successful export to save disk space.",
        ),
    ] = False,
) -> None:
    try:
        output = Exporter(input_dir, output_file, compact).run()
    except (OSError, ValueError, KeyError, ET.ParseError, FFmpegError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Video exported successfully! (Saved as: {output})")
