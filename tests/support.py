from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from ffmpeg import FFmpeg

from steamrecordingsexporter.template import Template

INITIALIZATION = "init-stream$RepresentationID$.m4s"
MEDIA = "chunk-stream$RepresentationID$-$Number%05d$.m4s"


def write_recording(
    folder: Path,
    streams: Mapping[str, Iterable[int]],
    *,
    initialization: str = INITIALIZATION,
    media: str = MEDIA,
    start_number: int = 1,
    duration: str | None = None,
    segment_duration: int | None = None,
) -> Path:
    """Write a recording whose chunks hold their own names, so a joined stream shows its order."""
    for rep_id, numbers in streams.items():
        names = [Template(initialization).format(rep_id)]
        names += [Template(media).format(rep_id, number) for number in numbers]
        for name in names:
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"{name};".encode())
    representations = "".join(f'<Representation id="{rep_id}"/>' for rep_id in streams)
    declared = f' mediaPresentationDuration="{duration}"' if duration else ""
    timing = f' duration="{segment_duration}"' if segment_duration else ""
    (folder / "session.mpd").write_text(
        f'<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"{declared}><Period><AdaptationSet>'
        f'<SegmentTemplate initialization="{initialization}" media="{media}"{timing}'
        f' startNumber="{start_number}"/>{representations}</AdaptationSet></Period></MPD>'
    )
    return folder.resolve()


def contents(folder: Path) -> dict[str, bytes]:
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in folder.rglob("*")
        if path.is_file()
    }


@dataclass
class FFmpegRun:
    arguments: list[str]
    inputs: list[Path]
    input_contents: list[bytes]


@contextmanager
def fake_ffmpeg(output: bytes = b"MP4") -> Iterator[list[FFmpegRun]]:
    """Stand in for FFmpeg, recording what each run reads and writing its output."""
    runs = []

    def execute(command: FFmpeg) -> None:
        arguments = command.arguments
        inputs = [
            Path(arguments[i + 1]) for i, argument in enumerate(arguments) if argument == "-i"
        ]
        runs.append(FFmpegRun(arguments, inputs, [path.read_bytes() for path in inputs]))
        Path(arguments[-1]).write_bytes(output)

    with patch.object(FFmpeg, "execute", autospec=True, side_effect=execute):
        yield runs
