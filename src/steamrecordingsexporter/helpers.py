import re
from collections.abc import Iterator
from typing import Optional


_TOKEN_PATTERN = re.compile(
    r"\$\$|\$(?P<name>[A-Za-z][A-Za-z0-9_]*)(?P<fmt>%[^$]+)?\$"
)
_FORMAT_PATTERN = re.compile(r"%0(?P<width>[1-9][0-9]*)d")
_SUPPORTED_IDENTIFIERS = {"RepresentationID", "Number"}


def _template_parts(template: str) -> Iterator[tuple[str, Optional[str], Optional[str]]]:
    """Yield (literal, identifier, format); literals have no identifier."""
    position = 0
    for match in _TOKEN_PATTERN.finditer(template):
        literal = template[position : match.start()]
        if "$" in literal:
            raise ValueError(f"Malformed DASH template: {template!r}")
        if literal:
            yield literal, None, None

        if match.group() == "$$":
            yield "$", None, None
        else:
            name = match.group("name")
            fmt = match.group("fmt")
            if name not in _SUPPORTED_IDENTIFIERS:
                raise ValueError(f"Unsupported DASH template identifier: {name}")
            if fmt is not None and _FORMAT_PATTERN.fullmatch(fmt) is None:
                raise ValueError(f"Unsupported DASH template format: {fmt}")
            yield "", name, fmt
        position = match.end()

    literal = template[position:]
    if "$" in literal:
        raise ValueError(f"Malformed DASH template: {template!r}")
    if literal:
        yield literal, None, None


def _format_value(name: str, fmt: Optional[str], values: dict) -> str:
    if name not in values:
        raise KeyError(f"Missing value for '{name}'")
    value = values[name]
    if fmt is None:
        return str(value)
    try:
        return fmt % int(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(
            f"DASH template identifier '{name}' requires an integer for format '{fmt}'"
        ) from exc


def get_filename(template: str, **kwargs) -> str:
    return "".join(
        literal if name is None else _format_value(name, fmt, kwargs)
        for literal, name, fmt in _template_parts(template)
    )


def get_filename_pattern(template: str, **kwargs) -> re.Pattern:
    """Leave $Number$ unresolved for segment discovery."""
    parts = []
    number_format = None
    found_number = False
    for literal, name, fmt in _template_parts(template):
        if name is None:
            parts.append(re.escape(literal))
        elif name == "Number":
            if "Number" in kwargs:
                raise ValueError("Number must remain unresolved in a media template")
            if found_number:
                if fmt != number_format:
                    raise ValueError("Repeated Number identifiers must use the same format")
                parts.append("(?P=Number)")
            else:
                width = int(_FORMAT_PATTERN.fullmatch(fmt).group("width")) if fmt else 1
                parts.append(r"(?P<Number>[0-9]{" + str(width) + r",})")
                number_format = fmt
                found_number = True
        else:
            parts.append(re.escape(_format_value(name, fmt, kwargs)))

    if not found_number:
        raise ValueError("Media template must contain the $Number$ identifier")
    return re.compile("".join(parts))
