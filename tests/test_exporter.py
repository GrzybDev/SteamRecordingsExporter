import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from ffmpeg import FFmpeg

from steamrecordingsexporter.errors import ExportError
from steamrecordingsexporter.exporter import Exporter
from steamrecordingsexporter.recording import load_recording
from support import write_recording


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
        write_recording(self.input_dir, dict(streams), initialization=initialization, media=media)
        self.session = self.input_dir / "session.mpd"
        return load_recording(self.input_dir)

    def test_join_preserves_sources_even_when_they_use_stream_filenames(self):
        reps = self.recording(initialization='stream-$RepresentationID$.m4s')
        stream_dir = self.root / 'streams'
        stream_dir.mkdir()
        paths = self.exporter.join_segments(reps.streams, stream_dir)
        self.assertEqual(paths[0].read_bytes(), b'stream-7.m4s;chunk-7-00001.m4s;chunk-7-00002.m4s;')
        self.assertEqual((self.input_dir / 'stream-7.m4s').read_bytes(), b'stream-7.m4s;')

    def test_chunk_removed_after_discovery_is_an_error(self):
        reps = self.recording()
        (self.input_dir / 'chunk-7-00002.m4s').unlink()
        with self.assertRaises(FileNotFoundError):
            self.exporter.join_segments(reps.streams, self.root)

    def test_output_cannot_overwrite_manifest_or_chunk(self):
        self.recording()
        for source in (self.session, self.input_dir / 'init-7.m4s', self.input_dir / 'chunk-7-00001.m4s'):
            with self.subTest(source=source):
                exporter = Exporter(self.input_dir, source, compact=True)
                with patch('shutil.which', return_value='ffmpeg'):
                    with self.assertRaisesRegex(ExportError, 'overwrite a recording source'):
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
            with self.assertRaisesRegex(ExportError, 'overwrite a recording source'):
                self.exporter.run()
        self.assertEqual(source.read_bytes(), b'chunk-7-00001.m4s;')

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

    def test_extensionless_output_gets_the_default_container(self):
        self.assertEqual(Exporter(self.input_dir, self.root / 'recording').output_file, self.output)

    def test_given_extension_is_kept(self):
        self.assertEqual(Exporter(self.input_dir, self.root / 'recording.mkv').output_file, self.root / 'recording.mkv')

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
            with self.assertRaisesRegex(ExportError, 'non-empty output'):
                self.exporter.run()
        self.assertEqual(self.output.read_bytes(), b'EXISTING')
        self.assertEqual({path.name: path.read_bytes() for path in self.input_dir.iterdir()}, before)

    def test_compact_removes_directories_it_emptied(self):
        self.recording(media='media/$RepresentationID$/chunk-$Number$.m4s')
        self.exporter.compact = True

        def execute(command):
            Path(command.arguments[-1]).write_bytes(b'MP4')

        with patch('shutil.which', return_value='ffmpeg'), patch.object(FFmpeg, 'execute', execute), redirect_stdout(io.StringIO()):
            self.exporter.run()
        self.assertEqual([path.name for path in self.input_dir.iterdir()], ['session.mpd'])

    def test_compact_keeps_directories_that_still_hold_other_files(self):
        self.recording(media='media/$RepresentationID$/chunk-$Number$.m4s')
        self.exporter.compact = True
        (self.input_dir / 'media' / '7' / 'notes.txt').write_bytes(b'keep')

        def execute(command):
            Path(command.arguments[-1]).write_bytes(b'MP4')

        with patch('shutil.which', return_value='ffmpeg'), patch.object(FFmpeg, 'execute', execute), redirect_stdout(io.StringIO()):
            self.exporter.run()
        self.assertEqual(
            sorted(path.relative_to(self.input_dir).as_posix() for path in self.input_dir.rglob('*')),
            ['media', 'media/7', 'media/7/notes.txt', 'session.mpd'],
        )

    def test_compact_keeps_going_when_a_chunk_cannot_be_removed(self):
        self.recording()
        self.exporter.compact = True
        locked = (self.input_dir / 'chunk-7-00001.m4s').resolve()
        unlink = Path.unlink

        def flaky_unlink(path, *args, **kwargs):
            if path == locked:
                raise PermissionError('chunk is locked')
            return unlink(path, *args, **kwargs)

        def execute(command):
            Path(command.arguments[-1]).write_bytes(b'MP4')

        with patch('shutil.which', return_value='ffmpeg'), patch.object(FFmpeg, 'execute', execute), \
                patch.object(Path, 'unlink', flaky_unlink), redirect_stdout(io.StringIO()):
            with self.assertLogs('steamrecordingsexporter.exporter', level='WARNING') as logs:
                self.assertEqual(self.exporter.run(), self.output)
        self.assertIn('chunk is locked', logs.output[0])
        self.assertEqual(self.output.read_bytes(), b'MP4')
        self.assertEqual(sorted(path.name for path in self.input_dir.iterdir()), ['chunk-7-00001.m4s', 'session.mpd'])


if __name__ == '__main__':
    unittest.main()
