# SteamRecordingsExporter

A command-line tool that exports Steam game recordings to single video files without the Steam client, including
recordings that lost some of their segments.

Table of Contents
-----------------

- [Legal notes](#legal-notes)
- [Features](#features)
- [Requirements](#requirements)
- [Installing](#installing)
- [Usage](#usage)
- [File formats](#file-formats)
- [Development](#development)
- [Credits](#credits)

Legal notes
-----------

SteamRecordingsExporter is not affiliated with or endorsed by Valve Corporation. Steam is a trademark of Valve
Corporation. The tool includes no Steam files; it reads only the recordings that Steam saved on your computer.

Features
--------

- Export a Steam recording folder to one video file with every video and audio track, without re-encoding
- Export recordings with missing segments and report which segments of each stream are missing, including the
  ones lost at the end
- Keep a stream that lost its first segments in sync with the others
- Shift the audio against the video by a set number of seconds (`--audio-offset`)
- Leave the recording untouched and replace an existing output only after a successful export
- Delete the recording's chunks after a successful export (`--compact`)
- Stop with an error that names the reason when a manifest uses something the tool cannot export

Requirements
------------

- [FFmpeg](https://ffmpeg.org) on PATH
- Python 3.14+ when installing from source

Installing
----------

Portable builds for Windows, macOS and Linux are on the
[Releases](https://github.com/GrzybDev/SteamRecordingsExporter/releases) page; the Windows build is code-signed.
You can also install the tool from the repository with uv (or pipx):

```sh
uv tool install git+https://github.com/GrzybDev/SteamRecordingsExporter
```

Usage
-----

```sh
steamrecordingsexporter --help
python -m steamrecordingsexporter --help
```

```sh
steamrecordingsexporter path/to/recording [path/to/output.mp4] [--compact] [--audio-offset SECONDS]
```

`path/to/recording` is a recording folder: the folder holding a `session.mpd` and the chunks it lists. Steam saves
each background recording in its own recording folder, `video/bg_<app id>_<date>_<time>`, inside the folder set in
its game recording settings.

The tool joins the chunks of each stream and merges the streams into one file with FFmpeg, without re-encoding.
Without an output, it saves `<recording folder name>.mp4` in the current folder; given an existing folder, it saves
the same name there; given any other name without an extension, it appends `.mp4`. FFmpeg picks the container from the
extension.

The joined streams go to a temporary `.steamrecordingsexporter-*` folder beside the output and are deleted afterwards,
so the output's drive needs free space for about twice the size of the recording. An existing output is replaced only
once FFmpeg has written a complete file, and the recording itself is never changed.

When segments are missing, the tool warns which segments of each stream are missing and exports the rest; the
declared length of the recording also reveals segments lost at the end. The video has nothing in place of the
missing segments. The last line names the output and counts the warnings.

`--compact` deletes the chunks only after the export succeeds, together with any folder they leave empty. It keeps
`session.mpd` and every other file. A chunk that cannot be deleted is reported as a warning.

`--audio-offset` delays every audio stream by the given number of seconds, or plays it earlier with a negative
value, to bring sound that runs behind or ahead of the picture back in sync. Only the timestamps move, so nothing
is re-encoded. The manifest marks which streams are audio.

The export stops with an error and exit code 1 when the recording folder has no `session.mpd`, the manifest is one the
tool cannot export (see [File formats](#file-formats)), a stream has no initialization chunk or no segments, FFmpeg is
missing or fails, the output folder does not exist, the output would overwrite a file of the recording, or an audio
offset is given for a recording without an audio stream. A representation without an ID or without segment templates
stops the whole export. Invalid arguments, such as a recording folder that does not exist, exit with code 2. Progress,
warnings and errors go to stderr; the last line goes to stdout.

|                   Option | Description                                                             | Default                                             |
|-------------------------:|-------------------------------------------------------------------------|-----------------------------------------------------|
|      `path/to/recording` | Recording folder holding `session.mpd` and the chunks it lists          | required                                            |
|     `path/to/output.mp4` | Output file, or the folder to save it in                                | `<recording folder name>.mp4` in the current folder |
|        `-c`, `--compact` | Delete the recording's chunks once the export succeeds                  | off                                                 |
| `--audio-offset SECONDS` | Delay the audio by this many seconds; a negative value plays it earlier | `0`                                                 |

Export a recording into an existing `videos` folder and delete its chunks afterwards (progress bars left out):

```sh
steamrecordingsexporter path/to/Recordings/video/bg_1234567_20260412_201500 videos --compact
```

```text
Warning: Stream '0' is missing 2 of 1246 segments (731-732), which the export leaves out
Warning: Stream '1' is missing 2 of 1246 segments (731-732), which the export leaves out
Exported with 2 warnings: /home/user/videos/bg_1234567_20260412_201500.mp4
```

File formats
------------

The tool reads a Steam recording folder: an MPEG-DASH manifest, `session.mpd`, and the fragmented MP4 chunks it
lists. [Steam recording folder](docs/steam-recording.md) describes the folder, the manifest fields the tool uses and
what it rejects. The output holds every stream of the recording, copied as recorded.

Development
-----------

```sh
uv sync
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy
```

The integration tests record a short DASH recording with FFmpeg and check the export with ffprobe; they are skipped
when either is missing from PATH.

Credits
-------

- [GrzybDev](https://grzyb.dev)

Thanks to:

- [FFmpeg](https://ffmpeg.org) (for merging the streams)

Special thanks to:

- Valve (for making Steam's game recording)
