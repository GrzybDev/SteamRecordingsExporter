import os
from dataclasses import dataclass
from pathlib import Path

from steamrecordingsexporter.errors import ExportError
from steamrecordingsexporter.manifest import Representation, parse_manifest

MANIFEST = "session.mpd"


@dataclass(frozen=True)
class Stream:
    id: str
    initialization: Path
    segments: tuple[Path, ...]
    missing: tuple[int, ...]

    @property
    def chunks(self) -> tuple[Path, ...]:
        return (self.initialization, *self.segments)


@dataclass(frozen=True)
class Recording:
    folder: Path
    streams: tuple[Stream, ...]

    @property
    def manifest(self) -> Path:
        return self.folder / MANIFEST

    @property
    def chunks(self) -> tuple[Path, ...]:
        # Streams may share an initialization chunk.
        return tuple(dict.fromkeys(chunk for stream in self.streams for chunk in stream.chunks))


def load_recording(folder: Path) -> Recording:
    folder = folder.resolve()
    manifest = folder / MANIFEST
    if not manifest.is_file():
        raise ExportError(f"{MANIFEST} was not found in {folder}")
    representations = parse_manifest(manifest.read_bytes())
    names = _file_names(folder)
    return Recording(folder, tuple(_stream(folder, rep, names) for rep in representations))


def _stream(folder: Path, representation: Representation, names: set[str]) -> Stream:
    rep_id, start = representation.id, representation.start_number
    initialization = _chunk(folder, representation.initialization.format(rep_id))
    if not initialization.is_file():
        raise ExportError(f"Stream {rep_id!r} has no initialization chunk {initialization.name}")
    numbers = sorted(n for n in representation.media.numbers(rep_id, names) if n >= start)
    if not numbers:
        raise ExportError(f"Stream {rep_id!r} has no media segments")
    missing = sorted(set(range(start, numbers[-1] + 1)).difference(numbers))
    return Stream(
        rep_id,
        initialization,
        tuple(_chunk(folder, representation.media.format(rep_id, n)) for n in numbers),
        tuple(missing),
    )


def _chunk(folder: Path, name: str) -> Path:
    path = Path(os.path.normpath(folder / name))
    if not path.is_relative_to(folder):
        raise ExportError(f"Chunk {name} is outside the recording folder")
    return path


def _file_names(folder: Path) -> set[str]:
    """Return the path of every file in the folder and its subfolders, relative to it."""

    # A folder that cannot be read must stop the export instead of passing for missing segments.
    def fail(error: OSError) -> None:
        raise error

    return {
        (Path(root) / name).relative_to(folder).as_posix()
        for root, _, files in os.walk(folder, onerror=fail)
        for name in files
    }
