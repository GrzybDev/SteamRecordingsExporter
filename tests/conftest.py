import shutil
import subprocess

import pytest

from support import FakeFFmpeg


@pytest.fixture
def ffmpeg(monkeypatch: pytest.MonkeyPatch) -> FakeFFmpeg:
    """Replace FFmpeg with a fake that the test can configure and inspect."""
    fake = FakeFFmpeg()
    monkeypatch.setattr(shutil, "which", lambda name: name)
    monkeypatch.setattr(subprocess, "run", fake.run)
    return fake
