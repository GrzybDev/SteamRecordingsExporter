from collections.abc import Iterable, Mapping
from pathlib import Path

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
    (folder / "session.mpd").write_text(
        '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period><AdaptationSet>'
        f'<SegmentTemplate initialization="{initialization}" media="{media}"'
        f' startNumber="{start_number}"/>{representations}</AdaptationSet></Period></MPD>'
    )
    return folder.resolve()


def contents(folder: Path) -> dict[str, bytes]:
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in folder.rglob("*")
        if path.is_file()
    }
