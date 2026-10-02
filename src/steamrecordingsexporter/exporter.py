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
        elif not output_file.suffix:
            # FFmpeg infers the output container from the filename extension.
            output_file = output_file.with_name(f"{output_file.name}.mp4")
        self.output_file = output_file.resolve()
        self.compact = compact

    def _chunk_path(self, filename: str) -> Path:
        path = (self.input_dir / filename).resolve()
        if Path(filename).is_absolute() or not path.is_relative_to(self.input_dir):
            raise ValueError(f"Chunk path must stay inside the input directory: {filename}")
        return path

    def _initialization_path(self, rep: Representation) -> Path:
        return self._chunk_path(get_filename(rep.initialization, RepresentationID=rep.id))

    def _media_path(self, rep: Representation, number: int) -> Path:
        return self._chunk_path(get_filename(rep.media, RepresentationID=rep.id, Number=number))

    def get_session_data(self, session_file: Path) -> list[Representation]:
        if not session_file.is_file():
            raise FileNotFoundError(f"Manifest file not found: {session_file}")
        representations = MPD(session_file.read_bytes()).get_representations()
        filenames = [
            (Path(directory) / filename).relative_to(self.input_dir).as_posix()
            for directory, _, files in os.walk(self.input_dir, onerror=_raise_scan_error)
            for filename in files
        ]

        for rep in representations:
            init_path = self._initialization_path(rep)
            if not init_path.is_file():
                raise FileNotFoundError(
                    f"Initialization chunk '{init_path.name}' not found for representation '{rep.id}'."
                )

            # Reject escaping templates even when no media segment matches.
            self._media_path(rep, rep.startNumber)
            pattern = get_filename_pattern(rep.media, RepresentationID=rep.id)
            numbers = []
            for filename in filenames:
                match = pattern.fullmatch(filename)
                if match is None:
                    continue
                number = int(match.group("Number"))
                if number < rep.startNumber:
                    continue
                expected = get_filename(rep.media, RepresentationID=rep.id, Number=number)
                if filename != expected:
                    continue
                self._chunk_path(expected)
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
        return [self._initialization_path(rep)] + [
            self._media_path(rep, number) for number in rep.segments.numbers
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
        # Windows requires the temporary file to be closed before FFmpeg opens it.
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
                # Missing initial chunks must not shift streams out of sync.
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
        sources = list(dict.fromkeys(source_files))
        directories = [
            directory
            for source in sources
            for directory in source.parents
            if directory != self.input_dir and directory.is_relative_to(self.input_dir)
        ]
        for source in sources:
            source.unlink()
        for directory in sorted(set(directories), key=lambda path: len(path.parts), reverse=True):
            try:
                if not any(directory.iterdir()):
                    directory.rmdir()
            except OSError:
                logger.debug("Could not remove emptied directory: %s", directory)

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
