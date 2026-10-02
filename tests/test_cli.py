import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from ffmpeg import FFmpegError
from typer.testing import CliRunner

from steamrecordingsexporter import app


class CLITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.runner = CliRunner()

    def test_help(self):
        result = self.runner.invoke(app, ['--help'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('--compact', result.output)

    def test_expected_failures_have_nonzero_exit_and_useful_message(self):
        errors = [FileNotFoundError('session.mpd missing'), ValueError('Invalid media template'),
                  ET.ParseError('Invalid XML'), FFmpegError('Invalid media', ['ffmpeg'])]
        for error in errors:
            with self.subTest(error=error), patch('steamrecordingsexporter.Exporter.run', side_effect=error):
                result = self.runner.invoke(app, [str(self.root)])
                self.assertEqual(result.exit_code, 1, result.output)
                self.assertIn(f'Error: {error}', result.output)
                self.assertNotIn('successfully', result.output)

    def test_success_reports_saved_path(self):
        output = self.root / 'clip.mp4'
        with patch('steamrecordingsexporter.Exporter.run', return_value=output):
            result = self.runner.invoke(app, [str(self.root)])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(str(output), result.output)


if __name__ == '__main__':
    unittest.main()
