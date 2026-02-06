from pathlib import Path

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
from steamrecordingsexporter.representation import Representation
from steamrecordingsexporter.segments_data import SegmentData


class Exporter:
    __stream_filename_template = "stream-$RepresentationID$.m4s"

    def __init__(
        self, input_dir: Path, output_file: Path | None = None, compact: bool = False
    ) -> None:
        self.input_dir = input_dir
        self.output_file = output_file
        self.compact = compact

    def get_session_data(self, session_file: Path) -> list[Representation]:
        __mpd = MPD(session_file.read_text())
        representations = __mpd.get_representations()

        for rep in representations:
            init_chunk_filename = get_filename(
                rep.initialization, RepresentationID=rep.id
            )

            if not (self.input_dir / init_chunk_filename).exists():
                typer.echo(
                    f"Error: Initialization chunk '{init_chunk_filename}' not found for representation ID '{rep.id}'. Cannot continue.",
                    err=True,
                )
                raise typer.Exit(code=1)

            seg_start_number = (
                int(rep.startNumber) if rep.startNumber is not None else 1
            )

            seg_data = {
                "min": seg_start_number,
                "max": None,
            }

            seg_end_number = seg_start_number

            while True:
                segment_filename = get_filename(
                    rep.media, RepresentationID=rep.id, Number=seg_end_number
                )

                if not (self.input_dir / segment_filename).exists():
                    break

                seg_end_number += 1

            seg_data["max"] = seg_end_number
            representations[rep.id].segments = SegmentData(**seg_data)

        return representations

    def join_segments(self, representations: list[Representation]) -> None:
        for rep in representations:
            stream_file = self.input_dir / get_filename(
                self.__stream_filename_template, RepresentationID=rep.id
            )

            with open(stream_file, "wb") as output_stream:
                chunk_filename = get_filename(
                    rep.initialization,
                    RepresentationID=rep.id,
                )

                chunk_path = self.input_dir / chunk_filename
                if not chunk_path.exists():
                    continue

                output_stream.write(chunk_path.read_bytes())
                output_stream.flush()

                if self.compact:
                    chunk_path.unlink()

                if rep.segments is None:
                    typer.echo(
                        f"Warning: No segment data found for representation ID '{rep.id}'. Skipping segment joining for this representation.",
                        err=True,
                    )
                    continue

                for seg_id in track(
                    range(
                        rep.segments.min,
                        rep.segments.max,
                    ),
                    description=f"Joining segments for media stream with ID: {rep.id}",
                ):
                    if seg_id == "init":
                        chunk_filename = get_filename(
                            rep.initialization,
                            RepresentationID=rep.id,
                        )
                    else:
                        chunk_filename = get_filename(
                            rep.media,
                            RepresentationID=rep.id,
                            Number=seg_id,
                        )

                    chunk_path = self.input_dir / chunk_filename

                    if not chunk_path.exists():
                        continue

                    output_stream.write(chunk_path.read_bytes())
                    output_stream.flush()

                    if self.compact:
                        chunk_path.unlink()

    def export(self, stream_ids: list[int]) -> None:
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
                    str(self.output_file)
                    if self.output_file
                    else f"{self.input_dir.name}.mp4",
                    {"codec": "copy"},
                )
            )

            for stream_id in stream_ids:
                stream_file = self.input_dir / get_filename(
                    self.__stream_filename_template, RepresentationID=stream_id
                )
                ffmpeg = ffmpeg.input(str(stream_file))

            ffmpeg.execute()
            progress.update(
                task,
                description="Video exported successfully! (Saved as: {})".format(
                    self.output_file
                    if self.output_file
                    else f"{self.input_dir.name}.mp4"
                ),
                advance=1,
            )

    def cleanup(self, stream_ids: list[int]) -> None:
        for stream_id in stream_ids:
            stream_file = self.input_dir / get_filename(
                self.__stream_filename_template, RepresentationID=stream_id
            )

            if stream_file.exists():
                stream_file.unlink()
