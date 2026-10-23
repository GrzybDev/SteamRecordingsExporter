# Steam recording folder

Steam's game recording saves each recording as an MPEG-DASH presentation: a manifest, `session.mpd`, and
fragmented MP4 chunks that each hold a few seconds of one stream. This page describes that folder and the parts of
the manifest that SteamRecordingsExporter reads.

## Layout

Steam saves each background recording in its own recording folder inside the folder set in its game recording
settings:

```text
<folder set in Steam>/
  video/
    bg_<app id>_<YYYYMMDD>_<HHMMSS>/
      session.mpd
      init-stream0.m4s
      init-stream1.m4s
      chunk-stream0-00001.m4s
      chunk-stream0-00002.m4s
      ...
      chunk-stream1-00001.m4s
      ...
```

| File                            | Content                                                                          |
|---------------------------------|----------------------------------------------------------------------------------|
| `session.mpd`                   | The DASH manifest, an XML document                                               |
| `init-stream<id>.m4s`           | The initialization segment of stream `<id>`: the MP4 header with its codec setup |
| `chunk-stream<id>-<number>.m4s` | Media segment `<number>` of stream `<id>`, numbered with at least five digits    |

The recordings Steam writes hold a video stream (`0`) and an audio stream (`1`) in segments of three seconds; the
tool exports every stream the manifest lists. A stream is restored by writing its initialization segment followed
by its media segments in numeric order; the tool does that for each stream and lets FFmpeg merge the streams.
Files in the recording folder that the templates do not name are ignored and kept. The tool does not use Steam's
other files beside `video/`, such as `clips/`, `timelines/` and `gamerecording.pb`.

When Steam discards the oldest part of a background recording, the first chunks are deleted and the manifest's
`startNumber` and `Period` `start` move forward together, so the first chunk on disk need not be number 1.

## Manifest

The manifest follows the MPEG-DASH schema (`urn:mpeg:dash:schema:mpd:2011`). The tool reads these elements and
attributes:

| Element                           | Attribute                   | Type               | Use                                                                                   |
|-----------------------------------|-----------------------------|--------------------|---------------------------------------------------------------------------------------|
| `MPD`                             | `mediaPresentationDuration` | ISO 8601 duration  | Length of the recording; it gives how many segments each stream should have           |
| `BaseURL`                         | text                        | path               | Only an empty value, `.` or `./` is accepted                                          |
| `Period`                          |                             |                    | Exactly one                                                                           |
| `AdaptationSet`                   |                             |                    | Groups the representations of one content type                                        |
| `AdaptationSet`, `Representation` | `contentType`, `mimeType`   | string             | `audio` or `audio/...` on either level marks the stream as audio for `--audio-offset` |
| `Representation`                  | `id`                        | string             | The stream's ID and the value of `$RepresentationID$`; required and unique            |
| `SegmentTemplate`                 | `initialization`            | template           | Path of the initialization segment; required, must not use `$Number$`                 |
| `SegmentTemplate`                 | `media`                     | template           | Path of a media segment; required, must use `$Number$`                                |
| `SegmentTemplate`                 | `startNumber`               | integer, 0 or more | Number of the first media segment; default 1; files numbered below it are ignored     |
| `SegmentTemplate`                 | `timescale`                 | integer, 1 or more | Units per second of `duration`; default 1                                             |
| `SegmentTemplate`                 | `duration`                  | integer, 1 or more | Length of one media segment in `timescale` units                                      |

A `SegmentTemplate` may sit on the `Period`, the `AdaptationSet` or the `Representation`; an attribute on a lower
level overrides the same attribute above it. Steam writes more attributes, such as codecs, bitrates and the
resolution, which the tool does not need.

### Templates

| Identifier           | Value                                                    |
|----------------------|----------------------------------------------------------|
| `$RepresentationID$` | The representation's `id`                                |
| `$Number$`           | The segment number                                       |
| `$Number%0<width>d$` | The segment number padded with zeros to `<width>` digits |
| `$$`                 | A literal `$`                                            |

Template paths are relative to the recording folder. A file counts as a segment only when its name is exactly what
the template gives for its number, so `chunk-stream0-7.m4s` is not segment 7 of
`chunk-stream$RepresentationID$-$Number%05d$.m4s`.

### Missing segments

The expected segments of a stream run from `startNumber` to the higher of the last segment on disk and the last
segment that the declared length holds:

```text
segments = ceil(mediaPresentationDuration × timescale / duration)
last     = startNumber + segments − 1
```

When the manifest declares no length or no segment duration, the range ends at the last segment on disk. Every
number in the range without a file is reported as missing.

### Rejected manifests

The tool stops with an error for a document that is not valid XML or not a DASH MPD, no `Period` or more than one,
a `BaseURL` other than an empty one, `.` or `./`, no representations, a representation without an ID or with an ID
used twice, a missing `initialization` or `media` template, a template with an unbalanced `$` or an identifier
other than those above (such as `$Time$` or `$Bandwidth$`), a remote URL, a path that leads outside the recording
folder, an invalid `startNumber` or `mediaPresentationDuration`, and an invalid `timescale` or `duration` when the
manifest declares its length.

## Example

A manifest that Steam wrote for a background recording whose first 57 minutes 42 seconds it had already discarded,
shortened:

```xml
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" mediaPresentationDuration="PT7M15.331S">
  <Period id="0" start="PT57M42.0S">
    <AdaptationSet id="0" contentType="video">
      <Representation id="0" mimeType="video/mp4" codecs="hev1.2.4.L123.B0" width="3840" height="2160">
        <SegmentTemplate timescale="1000000" duration="3000000"
            initialization="init-stream$RepresentationID$.m4s"
            media="chunk-stream$RepresentationID$-$Number%05d$.m4s" startNumber="1155"/>
      </Representation>
    </AdaptationSet>
    <AdaptationSet id="1" contentType="audio">
      <Representation id="1" mimeType="audio/mp4" codecs="mp4a.40.2" audioSamplingRate="48000">
        <SegmentTemplate timescale="1000000" duration="3000000"
            initialization="init-stream$RepresentationID$.m4s"
            media="chunk-stream$RepresentationID$-$Number%05d$.m4s" startNumber="1155"/>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>
```

- A segment lasts 3,000,000 / 1,000,000 = 3 seconds, and the period starts at (1155 − 1) × 3 s = 57 min 42 s.
- The recording lasts 435.331 seconds, so each stream should have ceil(435.331 / 3) = 146 segments, numbered 1155
  to 1300.
- The video stream is `init-stream0.m4s` followed by `chunk-stream0-01155.m4s` to `chunk-stream0-01300.m4s`; the
  audio stream uses the same names with `1`.
- If `chunk-stream0-01299.m4s` and `chunk-stream0-01300.m4s` are missing, the tool prints
  `Warning: Stream '0' is missing 2 of 146 segments (1299-1300), which the export leaves out` and exports the
  other 144 segments of that stream.
