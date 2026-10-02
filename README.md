# SteamRecordingsExporter

Tool to recover semi-corrupted Steam recordings and export Steam recordings without the Steam client.

Table of Contents
-----------------
- [Features](#features)
- [Requirements](#requirements)
- [Installing](#installing)
- [Usage](#usage)
- [Development](#development)
- [Credits](#credits)

Features
--------

- Join DASH `m4s` initialization and media segments into per-representation stream files.
- Merge joined streams into a single MP4 using `ffmpeg` (stream copy — no re-encoding).
- Optionally remove processed chunk files after a successful export (`--compact`).
- Parse local, numbered Steam DASH recordings, recover available segments despite gaps, and preserve all audio tracks.

Requirements
------------

- Python 3.9+
- System `ffmpeg` binary available on PATH.

Installing
----------

You can get pre-compiled build for Windows, MacOS and Linux from [Releases](https://github.com/GrzybDev/SteamRecordingsExporter/releases), these builds still require FFmpeg on PATH.

Or install from source or via pip. Example using `pip` (recommended to use a virtualenv or `pipx`/`uv`):

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

# Export and remove processed chunks after success
steamrecordingsexporter path/to/clip_folder --compact
```

CLI arguments and options

| Parameter     | Description                                                                 | Default / notes                                           |
|--------------:|:----------------------------------------------------------------------------:|:----------------------------------------------------------|
| `input_dir`   | Path to clip folder containing `session.mpd` and segment (`.m4s`) files      | required                                                  |
| `output_file` | Output file path or directory where the exported media will be saved        | if directory given, saved as `<input_dir.name>.mp4`; if omitted saved as `<input_dir.name>.mp4` in CWD; if the name has no extension, `.mp4` is appended |
| `--compact`   | Remove processed chunk files after a successful export                 | `False`                                                   |

Notes
-----

- The tool reads `session.mpd`, extracts representation `initialization` and `media` templates, resolves segment filenames and concatenates them in order.
- Merging is performed with `ffmpeg` via the Python `python-ffmpeg` wrapper and uses stream copy (`-c copy`) to avoid re-encoding.

- Missing segments produce a warning; all available numbered segments from `startNumber` onward are joined in numeric order. Missing media may leave gaps in the recovered recording.
- Temporary streams are isolated from the recording files and are removed after either success or failure. An existing output is replaced only after FFmpeg succeeds and produces a non-empty file.
- `--compact` deletes only consumed initialization and media chunks after the output has been saved, together with any directory they emptied. It preserves `session.mpd`, unrelated files, and directories that still hold something. Allow enough disk space for temporary streams and the output during export.
- Supported manifests have a single `Period`, local paths in `SegmentTemplate`, and `$RepresentationID$` / `$Number$` identifiers (including `$Number%05d$` and escaped `$$`). Time-based templates, nontrivial `BaseURL` paths, and multiple periods are rejected with an error.

Development
-----------

Install the package and run the standard-library test suite:

```sh
pip install .
python -m unittest discover -s tests -v
```

Integration tests generate a short DASH recording and verify the exported video and both audio tracks using FFmpeg and ffprobe. Both binaries must be on PATH; otherwise these tests are skipped. CI runs the suite on Python 3.9 and 3.14.

Credits
-------

- [GrzybDev](https://grzyb.dev)

Special thanks:
- Authors and maintainers of FFmpeg and the MPEG-DASH specification for the underlying technologies.
- Valve for creating such an amazing feature!
