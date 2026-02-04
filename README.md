# SteamRecordingsExporter

Tool to recover semi-corrupted Steam recordings and export Steam recordings without the Steam client.

Table of Contents
-----------------
- [Features](#features)
- [Requirements](#build-requirements)
- [Installing](#installing)
- [Usage](#usage)
- [Credits](#credits)

Features
--------

- Join DASH `m4s` initialization and media segments into per-representation stream files.
- Merge joined streams into a single MP4 using `ffmpeg` (stream copy — no re-encoding).
- Optionally remove processed chunk files to save disk space (`--compact`).
- Robust parsing of `session.mpd` to detect representation templates and segment filenames.

Requirements
------------

- Python 3.10+
- System `ffmpeg` binary available on PATH.
- Python packages: `python-ffmpeg`, `typer` (installable via pip or your environment manager).

Installing
----------

Install from source or via pip. Example using `pip` (recommended to use a virtualenv or `pipx`/`uv`):

```sh
pip install .
# or, using pipx for an isolated CLI install:
pipx install .
# or, using uv
uv tool install .
```

If you prefer installing directly from a remote Git repository, replace the source with your repository URL:

```sh
# using pipx
pipx install git+https://github.com/GrzybDev/SteamRecordingsExporter.git
# using uv
uv tool install git+https://github.com/GrzybDev/SteamRecordingsExporter.git
```

Usage
-----

```sh
steamrecordingsexporter --help
```

The tool expects an input directory containing DASH segment files and a `session.mpd` file describing representations.

- By default the tool will join representation segments, then merge them with `ffmpeg` into a single MP4 file using stream copy.
- If `output_file` is omitted the resulting file will be named `<clip-folder-name>.mp4` and saved to the current working directory.

Example:

```sh
# Export a clip folder to default output name
steamrecordingsexporter path/to/clip_folder

# Export and write to a specific file
steamrecordingsexporter path/to/clip_folder output.mp4

# Export and remove chunks as they are processed
steamrecordingsexporter path/to/clip_folder --compact
```

CLI arguments and options

| Parameter     | Description                                                                 | Default / notes                                           |
|--------------:|:----------------------------------------------------------------------------:|:----------------------------------------------------------|
| `input_dir`   | Path to clip folder containing `session.mpd` and segment (`.m4s`) files      | required                                                  |
| `output_file` | Output file path or directory where the exported media will be saved        | if directory given, saved as `<input_dir.name>.mp4`; if omitted saved as `<input_dir.name>.mp4` in CWD |
| `--compact`   | Remove processed chunk files immediately to save disk space                 | `False`                                                   |

Notes
-----

- The tool reads `session.mpd`, extracts representation `initialization` and `media` templates, resolves segment filenames and concatenates them in order.
- Merging is performed with `ffmpeg` via the Python `python-ffmpeg` wrapper and uses stream copy (`-c copy`) to avoid re-encoding.

Credits
-------

- [GrzybDev](https://grzyb.dev)
- Libraries and tools: `python-ffmpeg`, `typer`, `rich`, and `ffmpeg`.

Special thanks:
- Authors and maintainers of FFmpeg and the MPEG-DASH specification for the underlying technologies.
- Valve for creating such an amazing feature!
