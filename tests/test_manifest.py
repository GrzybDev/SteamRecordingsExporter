from pathlib import Path

import pytest

from steamrecordingsexporter.errors import ExportError
from steamrecordingsexporter.manifest import parse_manifest

STEAM_MANIFEST = Path(__file__).with_name("data") / "steam-session.mpd"

DEFAULT_TEMPLATE = '<SegmentTemplate initialization="init.m4s" media="$Number$.m4s"/>'


def manifest(period: str, attributes: str = "") -> bytes:
    """Return an MPD document around the period.

    Args:
        period: The Period elements.
        attributes: Extra attributes of the MPD element.
    """
    return f'<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" {attributes}>{period}</MPD>'.encode()


def single(template: str = DEFAULT_TEMPLATE, representation_id: str = "0") -> bytes:
    """Return an MPD document with one representation.

    Args:
        template: The representation's SegmentTemplate element.
        representation_id: The representation's ID.
    """
    return manifest(
        f'<Period><AdaptationSet><Representation id="{representation_id}">{template}'
        "</Representation></AdaptationSet></Period>"
    )


def test_reads_a_steam_manifest() -> None:
    representations = parse_manifest(STEAM_MANIFEST.read_bytes())
    assert [representation.id for representation in representations] == ["0", "1"]
    assert [representation.audio for representation in representations] == [False, True]
    for representation in representations:
        assert representation.start_number == 1155
        assert representation.segment_count == 146
        assert representation.initialization.format(representation.id) == (
            f"init-stream{representation.id}.m4s"
        )
        assert representation.media.format(representation.id, 1155) == (
            f"chunk-stream{representation.id}-01155.m4s"
        )


def test_segment_template_is_inherited_down_to_the_representation() -> None:
    [representation] = parse_manifest(
        manifest(
            '<Period><SegmentTemplate initialization="init-$RepresentationID$.m4s"'
            ' media="period-$Number$.m4s" startNumber="2"/><AdaptationSet>'
            '<SegmentTemplate media="set-$Number%05d$.m4s" startNumber="3"/>'
            '<Representation id="a"><SegmentTemplate startNumber="4"/></Representation>'
            "</AdaptationSet></Period>"
        )
    )
    assert representation.initialization.format("a") == "init-a.m4s"
    assert representation.media.format("a", 7) == "set-00007.m4s"
    assert representation.start_number == 4


@pytest.mark.parametrize(
    ("adaptation_set", "representation", "audio"),
    [
        ('contentType="audio"', "", True),
        ('mimeType="audio/mp4"', "", True),
        ("", 'mimeType="audio/mp4"', True),
        ('contentType="video"', 'mimeType="video/mp4"', False),
        ("", "", False),
    ],
)
def test_finds_audio_by_content_or_mime_type_on_either_level(
    adaptation_set: str, representation: str, audio: bool
) -> None:
    [found] = parse_manifest(
        manifest(
            f"<Period><AdaptationSet {adaptation_set}>"
            f'<Representation id="0" {representation}>{DEFAULT_TEMPLATE}</Representation>'
            "</AdaptationSet></Period>"
        )
    )
    assert found.audio is audio


@pytest.mark.parametrize(
    ("declared", "timing", "count"),
    [
        (
            'mediaPresentationDuration="PT1H52M42.109S"',
            'timescale="1000000" duration="3000000"',
            2255,
        ),
        ('mediaPresentationDuration="PT6S"', 'duration="3"', 2),
        ('mediaPresentationDuration="P1DT0.5S"', 'timescale="1000" duration="86400000"', 2),
        ("", 'duration="3"', None),
        ('mediaPresentationDuration="PT6S"', "", None),
    ],
)
def test_counts_the_segments_that_fill_the_declared_duration(
    declared: str, timing: str, count: int | None
) -> None:
    data = manifest(
        '<Period><AdaptationSet><Representation id="0"><SegmentTemplate'
        f' initialization="init.m4s" media="$Number$.m4s" {timing}/>'
        "</Representation></AdaptationSet></Period>",
        declared,
    )
    assert parse_manifest(data)[0].segment_count == count


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"<MPD", "not valid XML"),
        (b"<document/>", "not a DASH MPD"),
        (manifest("<BaseURL>elsewhere/</BaseURL><Period/>"), "BaseURL"),
        (manifest("<Period/><Period/>"), "one Period, not 2"),
        (manifest("<Period><AdaptationSet/></Period>"), "no representations"),
        (single(representation_id=" "), "no ID"),
        (
            manifest(
                "<Period><AdaptationSet>"
                + f'<Representation id="0">{DEFAULT_TEMPLATE}</Representation>' * 2
                + "</AdaptationSet></Period>"
            ),
            "used more than once: 0",
        ),
        (single("<SegmentTemplate media='$Number$.m4s'/>"), "no initialization"),
        (single("<SegmentTemplate initialization='init.m4s'/>"), "no media"),
        (
            single('<SegmentTemplate initialization="init.m4s" media="https://cdn/$Number$.m4s"/>'),
            "remote media",
        ),
        (single('<SegmentTemplate initialization="init.m4s" media="$Time$.m4s"/>'), r"\$Time\$"),
        (single('<SegmentTemplate initialization="init.m4s" media="chunk.m4s"/>'), "must use"),
        (
            single('<SegmentTemplate initialization="$Number$.m4s" media="$Number$.m4s"/>'),
            "must not use",
        ),
        (
            single(
                '<SegmentTemplate initialization="i.m4s" media="$Number$.m4s" startNumber="-1"/>'
            ),
            "invalid startNumber",
        ),
        (
            manifest(
                '<Period><SegmentTemplate initialization="i" media="$Number$" duration="0"/>'
                '<AdaptationSet><Representation id="0"/></AdaptationSet></Period>',
                'mediaPresentationDuration="PT6S"',
            ),
            "invalid duration",
        ),
        (
            manifest("<Period/>", 'mediaPresentationDuration="7 minutes"'),
            "Invalid mediaPresentationDuration",
        ),
    ],
)
def test_rejects_manifests_it_cannot_export(data: bytes, message: str) -> None:
    with pytest.raises(ExportError, match=message):
        parse_manifest(data)
