import logging
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Optional

from ffmpeg import FFmpeg
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn, track

from steamrecordingsexporter.errors import ExportError
from steamrecordingsexporter.recording import Stream, load_recording

logger = logging.getLogger(__name__)


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

    def join_segments(self, streams: tuple[Stream, ...], stream_dir: Path) -> list[Path]:
        stream_files = []
        for index, stream in enumerate(streams):
            stream_file = stream_dir / f"stream-{index}.m4s"
            with stream_file.open("wb") as output_stream:
                for chunk_path in track(
                    stream.chunks,
                    description=f"Joining segments for media stream with ID: {stream.id}",
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
                raise ExportError(f"Output file would overwrite a recording source: {source}")

    def export(self, stream_files: list[Path]) -> None:
        if not stream_files:
            raise ExportError("No streams to export.")
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
                    raise ExportError("FFmpeg did not produce a non-empty output file.")
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
            try:
                source.unlink(missing_ok=True)
            except OSError as error:
                logger.warning("Could not remove processed chunk %s: %s", source, error)
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
        recording = load_recording(self.input_dir)
        for stream in recording.streams:
            if stream.missing:
                logger.warning(
                    "Missing segments for representation '%s'; recovering the available "
                    "segments. The recording may contain gaps.",
                    stream.id,
                )
        self._validate_output([recording.manifest, *recording.chunks])
        with TemporaryDirectory(prefix="steamrecordingsexporter-") as directory:
            stream_files = self.join_segments(recording.streams, Path(directory))
            self.export(stream_files)
        if self.compact:
            self.cleanup(list(recording.chunks))
        return self.output_file
