import re


def get_filename(template: str, **kwargs) -> str:
    pattern = re.compile(r"\$(?P<name>[A-Za-z0-9_]+)(?P<fmt>%[^$]+)?\$")

    def _repl(m: re.Match) -> str:
        name = m.group("name")
        fmt = m.group("fmt")

        if name not in kwargs:
            raise KeyError(f"Missing value for '{name}'")

        val = kwargs[name]

        if fmt:
            try:
                return fmt % int(val)
            except Exception:
                # Fallback: try to apply fmt with Python's % operator
                try:
                    return fmt % val  # type: ignore
                except Exception:
                    return str(val)

        return str(val)

    return pattern.sub(_repl, template)
