import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from ffmpeg import FFmpeg

from steamrecordingsexporter.exporter import Exporter


class ExporterTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.input_dir = self.root / "clip"
        self.input_dir.mkdir()
        self.output = self.root / "recording.mp4"
        self.exporter = Exporter(self.input_dir, self.output)
        self.addCleanup(patch.stopall)
        patch("steamrecordingsexporter.exporter.track", side_effect=lambda items, **kwargs: items).start()

    def recording(self, streams=(('7', (1, 2)),), initialization="init-$RepresentationID$.m4s", media="chunk-$RepresentationID$-$Number%05d$.m4s"):
        from steamrecordingsexporter.helpers import get_filename

        representations = []
        for rep_id, numbers in streams:
            representations.append(f'<Representation id="{rep_id}"/>')
            init = self.input_dir / get_filename(initialization, RepresentationID=rep_id)
            init.parent.mkdir(parents=True, exist_ok=True)
            init.write_bytes(f"INIT:{rep_id};".encode())
            for number in numbers:
                chunk = self.input_dir / get_filename(media, RepresentationID=rep_id, Number=number)
                chunk.parent.mkdir(parents=True, exist_ok=True)
                chunk.write_bytes(f"{rep_id}:{number};".encode())
        self.session = self.input_dir / "session.mpd"
        self.session.write_text(
            '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period><AdaptationSet>'
            f'<SegmentTemplate initialization="{initialization}" media="{media}"/>'
            + ''.join(representations) + '</AdaptationSet></Period></MPD>', encoding="utf-8",
        )
        return self.exporter.get_session_data(self.session)

    def test_nonconsecutive_and_string_ids_keep_their_own_segments(self):
        reps = self.recording((('audio-main', (1, 2, 3)), ('42', (1,)), ('0', (1, 2))))
        self.assertEqual([(rep.id, rep.segments.numbers) for rep in reps], [
            ('audio-main', (1, 2, 3)), ('42', (1,)), ('0', (1, 2)),
        ])

    def test_gaps_and_missing_first_segment_do_not_truncate_recovery(self):
        with self.assertLogs("steamrecordingsexporter.exporter", level="WARNING"):
            reps = self.recording((('7', (2, 3, 5, 10)),))
        self.assertEqual(reps[0].segments.numbers, (2, 3, 5, 10))

    def test_discovery_ignores_noncanonical_or_unrelated_filenames(self):
        self.recording()
        for name in ('chunk-7-3.m4s', 'chunk-7-00003.m4s.bak', 'chunk-8-00003.m4s', 'chunk-7-00000.m4s'):
            (self.input_dir / name).write_bytes(b"unrelated")
        reps = self.exporter.get_session_data(self.session)
        self.assertEqual(reps[0].segments.numbers, (1, 2))

    def test_nested_media_paths_are_supported(self):
        reps = self.recording(media='media/$RepresentationID$/chunk-$Number$.m4s')
        self.assertEqual(reps[0].segments.numbers, (1, 2))

    def test_missing_initialization_is_an_error(self):
        self.recording()
        (self.input_dir / 'init-7.m4s').unlink()
        with self.assertRaisesRegex(FileNotFoundError, "Initialization chunk"):
            self.exporter.get_session_data(self.session)

    def test_unreadable_directory_is_an_error_before_export(self):
        self.recording()
        with patch('os.scandir', side_effect=PermissionError('Cannot scan recording')):
            with self.assertRaisesRegex(PermissionError, 'Cannot scan recording'):
                self.exporter.get_session_data(self.session)

    def test_init_without_media_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "No media segments"):
            self.recording((('7', ()),))

    def test_chunk_path_cannot_escape_input_directory(self):
        outside = self.root / 'init-7.m4s'
        outside.write_bytes(b"untouched")
        with self.assertRaisesRegex(ValueError, "inside the input directory"):
            self.recording(initialization='../init-$RepresentationID$.m4s')
        self.assertTrue(outside.is_file())

    def test_join_preserves_sources_even_when_they_use_stream_filenames(self):
        reps = self.recording(initialization='stream-$RepresentationID$.m4s')
        stream_dir = self.root / 'streams'
        stream_dir.mkdir()
        paths = self.exporter.join_segments(reps, stream_dir)
        self.assertEqual(paths[0].read_bytes(), b'INIT:7;7:1;7:2;')
        self.assertEqual((self.input_dir / 'stream-7.m4s').read_bytes(), b'INIT:7;')

    def test_chunk_removed_after_discovery_is_an_error(self):
        reps = self.recording()
        (self.input_dir / 'chunk-7-00002.m4s').unlink()
        with self.assertRaises(FileNotFoundError):
            self.exporter.join_segments(reps, self.root)

    def test_output_cannot_overwrite_manifest_or_chunk(self):
        self.recording()
        for source in (self.session, self.input_dir / 'init-7.m4s', self.input_dir / 'chunk-7-00001.m4s'):
            with self.subTest(source=source):
                exporter = Exporter(self.input_dir, source, compact=True)
                with patch('shutil.which', return_value='ffmpeg'):
                    with self.assertRaisesRegex(ValueError, 'overwrite a recording source'):
                        exporter.run()
                self.assertTrue(source.is_file())

    def test_output_hardlink_to_source_is_rejected(self):
        import os

        self.recording()
        source = self.input_dir / 'chunk-7-00001.m4s'
        try:
            os.link(source, self.output)
        except OSError as error:
            self.skipTest(f'Hardlinks unavailable: {error}')
        with patch('shutil.which', return_value='ffmpeg'):
            with self.assertRaisesRegex(ValueError, 'overwrite a recording source'):
                self.exporter.run()
        self.assertEqual(source.read_bytes(), b'7:1;')

    def test_missing_ffmpeg_preserves_sources(self):
        self.recording()
        with patch('shutil.which', return_value=None):
            with self.assertRaisesRegex(FileNotFoundError, 'FFmpeg was not found'):
                self.exporter.run()
        self.assertTrue((self.input_dir / 'init-7.m4s').is_file())

    def test_relative_dot_input_has_a_meaningful_default_output(self):
        with patch('pathlib.Path.cwd', return_value=self.root):
            exporter = Exporter(Path('.'))
        self.assertEqual(exporter.output_file.name, f'{Path.cwd().name}.mp4')
        self.assertNotEqual(exporter.output_file.name, '.mp4')

    def test_directory_output_uses_clip_name(self):
        exporter = Exporter(self.input_dir, self.root)
        self.assertEqual(exporter.output_file, self.root / 'clip.mp4')

    def test_successful_compact_export_removes_only_consumed_chunks(self):
        self.recording((('7', (1, 2)), ('8', (1,))), initialization='shared-init.m4s')
        self.exporter.compact = True
        unrelated = self.input_dir / 'unrelated.m4s'
        unrelated.write_bytes(b'keep')
        commands = []

        def execute(command):
            commands.append(command.arguments)
            self.assertTrue((self.input_dir / 'shared-init.m4s').is_file())
            Path(command.arguments[-1]).write_bytes(b'MP4')

        with patch('shutil.which', return_value='ffmpeg'), patch.object(FFmpeg, 'execute', execute), redirect_stdout(io.StringIO()):
            self.assertEqual(self.exporter.run(), self.output)
        self.assertEqual(self.output.read_bytes(), b'MP4')
        self.assertEqual(sorted(path.name for path in self.input_dir.iterdir()), ['session.mpd', 'unrelated.m4s'])
        arguments = commands[0]
        self.assertEqual([arguments[index + 1] for index, arg in enumerate(arguments) if arg == '-map'], ['0', '1'])
        self.assertIn('-nostdin', arguments)
        self.assertEqual(list(self.root.glob('.steam-export-*')), [])

    def test_failed_export_preserves_existing_output_and_compact_sources(self):
        self.recording()
        self.exporter.compact = True
        self.output.write_bytes(b'EXISTING')
        before = {path.name: path.read_bytes() for path in self.input_dir.iterdir()}
        temporary_stream_dirs = []

        def execute(command):
            arguments = command.arguments
            temporary_stream_dirs.append(Path(arguments[arguments.index('-i') + 1]).parent)
            Path(arguments[-1]).write_bytes(b'PARTIAL')
            raise RuntimeError('simulated FFmpeg failure')

        with patch('shutil.which', return_value='ffmpeg'), patch.object(FFmpeg, 'execute', execute), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'simulated FFmpeg failure'):
                self.exporter.run()
        self.assertEqual(self.output.read_bytes(), b'EXISTING')
        self.assertEqual({path.name: path.read_bytes() for path in self.input_dir.iterdir()}, before)
        self.assertEqual(list(self.root.glob('.steam-export-*')), [])
        self.assertFalse(temporary_stream_dirs[0].exists())

    def test_empty_ffmpeg_output_preserves_sources_and_existing_output(self):
        self.recording()
        self.exporter.compact = True
        self.output.write_bytes(b'EXISTING')
        before = {path.name: path.read_bytes() for path in self.input_dir.iterdir()}
        with patch('shutil.which', return_value='ffmpeg'), patch.object(FFmpeg, 'execute'), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, 'non-empty output'):
                self.exporter.run()
        self.assertEqual(self.output.read_bytes(), b'EXISTING')
        self.assertEqual({path.name: path.read_bytes() for path in self.input_dir.iterdir()}, before)

    def test_compact_deduplicates_shared_initialization_path_aliases(self):
        self.recording((('7', (1,)), ('8', (1,))), initialization='shared-init.m4s')
        self.session.write_text(self.session.read_text().replace(
            '<Representation id="8"/>',
            '<Representation id="8"><SegmentTemplate initialization="subdir/../shared-init.m4s"/></Representation>',
        ))
        self.exporter.compact = True

        def execute(command):
            Path(command.arguments[-1]).write_bytes(b'MP4')

        with patch('shutil.which', return_value='ffmpeg'), patch.object(FFmpeg, 'execute', execute), redirect_stdout(io.StringIO()):
            self.exporter.run()
        self.assertEqual([path.name for path in self.input_dir.iterdir()], ['session.mpd'])


if __name__ == '__main__':
    unittest.main()
