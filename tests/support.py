import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from steamrecordingsexporter.template import Template

INITIALIZATION = "init-stream$RepresentationID$.m4s"
MEDIA = "chunk-stream$RepresentationID$-$Number%05d$.m4s"


@dataclass
class FFmpegRun:
    """The arguments of one FFmpeg run and the bytes of its inputs when it ran."""

    arguments: Sequence[str]
    input_contents: list[bytes]


@dataclass
class FakeFFmpeg:
    """Stands in for FFmpeg: records each run, writes the configured output and exits as told."""

    output: bytes = b"MP4"
    returncode: int = 0
    stderr: str = ""
    runs: list[FFmpegRun] = field(default_factory=list)

    def run(self, arguments: Sequence[str], **options: Any) -> subprocess.CompletedProcess[str]:
        """Record a run and return or raise as subprocess.run would for the configured result.

        Args:
            arguments: The FFmpeg arguments, ending with the output path.
            options: The subprocess.run options, of which check and capture_output take effect.
        """
        inputs = [Path(arguments[i + 1]) for i, value in enumerate(arguments) if value == "-i"]
        self.runs.append(FFmpegRun(arguments, [path.read_bytes() for path in inputs]))
        Path(arguments[-1]).write_bytes(self.output)
        stderr = self.stderr if options.get("capture_output") else None
        result = subprocess.CompletedProcess(arguments, self.returncode, "", stderr)
        if options.get("check"):
            result.check_returncode()
        return result


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
    """Write a recording whose chunks hold their own names, so a joined stream shows its order.

    Args:
        folder: The recording folder to create.
        streams: The segment numbers to write for each representation ID.
        initialization: The SegmentTemplate initialization path.
        media: The SegmentTemplate media path.
        start_number: The SegmentTemplate startNumber.
        duration: The mediaPresentationDuration to declare, if any.
        segment_duration: The SegmentTemplate duration in seconds, if any.
    """
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
    """Return the bytes of every file in the folder and its subfolders by relative path.

    Args:
        folder: The folder to read.
    """
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in folder.rglob("*")
        if path.is_file()
    }
