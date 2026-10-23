import os
from dataclasses import dataclass
from pathlib import Path

from steamrecordingsexporter import messages
from steamrecordingsexporter.errors import ExportError
from steamrecordingsexporter.manifest import Representation, parse_manifest

MANIFEST = "session.mpd"


@dataclass(frozen=True)
class Stream:
    """The chunks of a stream found on disk and the numbers of its missing segments."""

    id: str
    initialization: Path
    segments: tuple[Path, ...]
    missing: tuple[int, ...]
    audio: bool

    @property
    def chunks(self) -> tuple[Path, ...]:
        """The initialization chunk followed by the segments in order."""
        return (self.initialization, *self.segments)


@dataclass(frozen=True)
class Recording:
    folder: Path
    streams: tuple[Stream, ...]

    @property
    def manifest(self) -> Path:
        """The manifest of the recording."""
        return self.folder / MANIFEST

    @property
    def chunks(self) -> tuple[Path, ...]:
        """Every chunk of the recording, each listed once."""
        # Streams may share an initialization chunk.
        return tuple(dict.fromkeys(chunk for stream in self.streams for chunk in stream.chunks))


def load_recording(folder: Path) -> Recording:
    """Read the manifest of the recording and find the chunks of each stream.

    Args:
        folder: The recording folder holding session.mpd.

    Raises:
        ExportError: If the manifest or the chunks of a stream cannot be used.
    """
    folder = folder.resolve()
    manifest = folder / MANIFEST
    if not manifest.is_file():
        raise ExportError(messages.MANIFEST_MISSING.format(manifest=MANIFEST, folder=folder))
    representations = parse_manifest(manifest.read_bytes())
    names = _file_names(folder)
    return Recording(folder, tuple(_stream(folder, rep, names) for rep in representations))


def _stream(folder: Path, representation: Representation, names: set[str]) -> Stream:
    rep_id, start = representation.id, representation.start_number
    initialization = _chunk(folder, representation.initialization.format(rep_id))
    if not initialization.is_file():
        raise ExportError(
            messages.INITIALIZATION_MISSING.format(id=rep_id, name=initialization.name)
        )
    numbers = sorted(n for n in representation.media.numbers(rep_id, names) if n >= start)
    if not numbers:
        raise ExportError(messages.SEGMENTS_MISSING.format(id=rep_id))
    # Steam declares the length of the recording, which also reveals segments lost at its end.
    last = max(numbers[-1], start + (representation.segment_count or 0) - 1)
    missing = sorted(set(range(start, last + 1)).difference(numbers))
    return Stream(
        rep_id,
        initialization,
        tuple(_chunk(folder, representation.media.format(rep_id, n)) for n in numbers),
        tuple(missing),
        representation.audio,
    )


def _chunk(folder: Path, name: str) -> Path:
    """Return the path of a chunk, refusing one outside the recording folder."""
    path = Path(os.path.normpath(folder / name))
    if not path.is_relative_to(folder):
        raise ExportError(messages.CHUNK_OUTSIDE.format(name=name))
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
