import pytest

from steamrecordingsexporter.template import Template


def test_formats_identifiers_with_padding_and_escaped_dollars() -> None:
    template = Template("$$Number$$/$RepresentationID$-$Number%05d$.m4s")
    assert template.format("audio", 7) == "$Number$/audio-00007.m4s"
    assert template.format("audio", 123456) == "$Number$/audio-123456.m4s"


def test_finds_segment_numbers_only_in_names_the_template_gives() -> None:
    template = Template("chunk-stream$RepresentationID$-$Number%05d$.m4s")
    names = [
        "chunk-stream0-00001.m4s",
        "chunk-stream0-123456.m4s",
        "chunk-stream0-7.m4s",
        "chunk-stream0-000002.m4s",
        "chunk-stream0-00003.m4s.bak",
        "chunk-stream1-00004.m4s",
        "init-stream0.m4s",
    ]
    assert template.numbers("0", names) == {1, 123456}
    nested = Template("$RepresentationID$/$Number$.m4s")
    assert nested.numbers("a+", ["a+/4.m4s", "aa/5.m4s"]) == {4}


@pytest.mark.parametrize(
    "text",
    [
        "$Time$.m4s",
        "$Bandwidth$",
        "$Number%5d$",
        "$Number%d$",
        "$RepresentationID%05d$",
        "$Number",
        "a$b",
    ],
)
def test_rejects_identifiers_it_cannot_resolve(text: str) -> None:
    with pytest.raises(ValueError):
        Template(text)
