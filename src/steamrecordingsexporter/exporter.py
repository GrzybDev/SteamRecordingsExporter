import logging
import os
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Optional

from ffmpeg import FFmpeg
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn, track

from steamrecordingsexporter.helpers import get_filename, get_filename_pattern
from steamrecordingsexporter.mpd import MPD
from steamrecordingsexporter.representation import Representation
from steamrecordingsexporter.segments_data import SegmentData

logger = logging.getLogger(__name__)


def _raise_scan_error(error: OSError) -> None:
    raise error


class Exporter:
    def __init__(
        self, input_dir: Path, output_file: Optional[Path] = None, compact: bool = False
    ) -> None:
        self.input_dir = input_dir.resolve()
        output_file = output_file if output_file is not None else Path.cwd()
        if output_file.is_dir():
            output_file /= f"{self.input_dir.name}.mp4"
        self.output_file = output_file.resolve()
        self.compact = compact

    def _chunk_path(self, filename: str) -> Path:
        path = (self.input_dir / filename).resolve()
        if Path(filename).is_absolute() or not path.is_relative_to(self.input_dir):
            raise ValueError(f"Chunk path must stay inside the input directory: {filename}")
        return path

    def get_session_data(self, session_file: Path) -> list[Representation]:
        representations = MPD(session_file.read_bytes()).get_representations()
        filenames = [
            (Path(directory) / filename).relative_to(self.input_dir).as_posix()
            for directory, _, files in os.walk(self.input_dir, onerror=_raise_scan_error)
            for filename in files
        ]

        for rep in representations:
            init_path = self._chunk_path(
                get_filename(rep.initialization, RepresentationID=rep.id)
            )
            if not init_path.is_file():
                raise FileNotFoundError(
                    f"Initialization chunk '{init_path.name}' not found for representation '{rep.id}'."
                )

            # Validate the path before discovery, including templates with subdirectories.
            self._chunk_path(
                get_filename(rep.media, RepresentationID=rep.id, Number=rep.startNumber)
            )
            pattern = get_filename_pattern(rep.media, RepresentationID=rep.id)
            numbers = []
            for filename in filenames:
                match = pattern.fullmatch(filename)
                if match is None:
                    continue
                number = int(match.group("Number"))
                if number < rep.startNumber:
                    continue
                if filename != get_filename(
                    rep.media, RepresentationID=rep.id, Number=number
                ):
                    continue
                self._chunk_path(filename)
                numbers.append(number)

            numbers.sort()
            if not numbers:
                raise ValueError(f"No media segments found for representation '{rep.id}'.")
            if numbers[0] != rep.startNumber or any(
                b != a + 1 for a, b in zip(numbers, numbers[1:])
            ):
                logger.warning(
                    "Missing segments for representation '%s'; recovering the available segments. "
                    "The recording may contain gaps.",
                    rep.id,
                )
            rep.segments = SegmentData(tuple(numbers))

        return representations

    def _chunk_paths(self, rep: Representation) -> list[Path]:
        if rep.segments is None or not rep.segments.numbers:
            raise ValueError(f"No segment data for representation '{rep.id}'.")
        initialization = self._chunk_path(
            get_filename(rep.initialization, RepresentationID=rep.id)
        )
        return [initialization] + [
            self._chunk_path(
                get_filename(rep.media, RepresentationID=rep.id, Number=number)
            )
            for number in rep.segments.numbers
        ]

    def join_segments(
        self, representations: list[Representation], stream_dir: Path
    ) -> list[Path]:
        stream_files = []
        for index, rep in enumerate(representations):
            stream_file = stream_dir / f"stream-{index}.m4s"
            with stream_file.open("wb") as output_stream:
                for chunk_path in track(
                    self._chunk_paths(rep),
                    description=f"Joining segments for media stream with ID: {rep.id}",
                ):
                    with chunk_path.open("rb") as chunk_stream:
                        shutil.copyfileobj(
                            chunk_stream, output_stream, length=1024 * 1024
                        )
            stream_files.append(stream_file)
        return stream_files

    def _validate_output(self, source_files: list[Path]) -> None:
        if not self.output_file.parent.is_dir():
            raise FileNotFoundError(f"Output directory does not exist: {self.output_file.parent}")
        for source in source_files:
            if source.resolve() == self.output_file or (
                self.output_file.exists() and self.output_file.samefile(source)
            ):
                raise ValueError(f"Output file would overwrite a recording source: {source}")

    def export(self, stream_files: list[Path]) -> None:
        if not stream_files:
            raise ValueError("No streams to export.")
        # Close the handle before FFmpeg opens the file, including on Windows.
        with NamedTemporaryFile(
            dir=self.output_file.parent,
            prefix=".steam-export-",
            suffix=self.output_file.suffix,
            delete=False,
        ) as temporary_file:
            temporary_output = Path(temporary_file.name)
        try:
            with Progress(
                SpinnerColumn(spinner_name="line", finished_text="done"),
                TextColumn("[progress.description]{task.description}"),
                TimeElapsedColumn(),
            ) as progress:
                task = progress.add_task(
                    description="Merging streams into final output file...", total=1
                )
                # Keep relative timing when the first chunk of one stream is missing.
                ffmpeg = FFmpeg().option("y").option("nostdin").option("copyts")
                for stream_file in stream_files:
                    ffmpeg.input(str(stream_file))
                ffmpeg.output(
                    str(temporary_output),
                    {
                        "codec": "copy",
                        "map": [str(index) for index in range(len(stream_files))],
                        "avoid_negative_ts": "make_zero",
                    },
                ).execute()
                if temporary_output.stat().st_size == 0:
                    raise ValueError("FFmpeg did not produce a non-empty output file.")
                temporary_output.replace(self.output_file)
                progress.update(task, advance=1)
        finally:
            temporary_output.unlink(missing_ok=True)

    def cleanup(self, source_files: list[Path]) -> None:
        for source in dict.fromkeys(source_files):
            source.unlink()

    def run(self) -> Path:
        if shutil.which("ffmpeg") is None:
            raise FileNotFoundError(
                "FFmpeg was not found on PATH. Install FFmpeg before exporting."
            )
        session_file = self.input_dir / "session.mpd"
        representations = self.get_session_data(session_file)
        source_files = [
            path for rep in representations for path in self._chunk_paths(rep)
        ]
        self._validate_output([session_file, *source_files])
        with TemporaryDirectory(prefix="steamrecordingsexporter-") as directory:
            stream_files = self.join_segments(representations, Path(directory))
            self.export(stream_files)
        if self.compact:
            self.cleanup(source_files)
        return self.output_file
