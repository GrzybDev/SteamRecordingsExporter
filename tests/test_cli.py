import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ffmpeg import FFmpegError
from rich.text import Text
from typer.testing import CliRunner

from steamrecordingsexporter import app
from steamrecordingsexporter.errors import ExportError


class CLITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.runner = CliRunner()
        self._isolate_logging()

    def _isolate_logging(self):
        """Keep the logging configuration the CLI installs from leaking into other tests."""
        root_logger = logging.getLogger()
        handlers, level = root_logger.handlers[:], root_logger.level

        def restore():
            root_logger.handlers[:] = handlers
            root_logger.setLevel(level)

        self.addCleanup(restore)

    def test_help(self):
        for color in (False, True):
            with self.subTest(color=color), patch(
                'typer.rich_utils.FORCE_TERMINAL', color
            ), patch.dict('os.environ', {'TERM': 'xterm-256color', 'NO_COLOR': ''}):
                result = self.runner.invoke(app, ['--help'], color=color)
                self.assertEqual(result.exit_code, 0, result.output)
                if color:
                    self.assertIn('\x1b[', result.output)
                self.assertIn('--compact', Text.from_ansi(result.output).plain)

    def test_expected_failures_have_nonzero_exit_and_useful_message(self):
        errors = [FileNotFoundError('session.mpd missing'), ExportError('Invalid media template'),
                  FFmpegError('Invalid media', ['ffmpeg'])]
        for error in errors:
            with self.subTest(error=error), patch('steamrecordingsexporter.Exporter.run', side_effect=error):
                result = self.runner.invoke(app, [str(self.root)])
                self.assertEqual(result.exit_code, 1, result.output)
                self.assertIn(f'Error: {error}', result.output)
                self.assertNotIn('successfully', result.output)

    def test_exporter_warnings_are_labelled_for_the_user(self):
        def warn_then_export():
            logging.getLogger('steamrecordingsexporter.exporter').warning('Recording may contain gaps')
            return self.root / 'clip.mp4'

        with patch('steamrecordingsexporter.Exporter.run', side_effect=warn_then_export):
            result = self.runner.invoke(app, [str(self.root)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('WARNING: Recording may contain gaps', result.output)

    def test_compact_flag_reaches_the_exporter(self):
        for flag, expected in (([], False), (['--compact'], True), (['-c'], True)):
            with self.subTest(flag=flag):
                with patch('steamrecordingsexporter.Exporter.__init__', return_value=None) as init, \
                        patch('steamrecordingsexporter.Exporter.run', return_value=self.root / 'clip.mp4'):
                    result = self.runner.invoke(app, [str(self.root), *flag])
                self.assertEqual(result.exit_code, 0, result.output)
                init.assert_called_once_with(self.root, None, expected)

    def test_success_reports_saved_path(self):
        output = self.root / 'clip.mp4'
        with patch('steamrecordingsexporter.Exporter.run', return_value=output):
            result = self.runner.invoke(app, [str(self.root)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(str(output), result.output)


if __name__ == '__main__':
    unittest.main()
