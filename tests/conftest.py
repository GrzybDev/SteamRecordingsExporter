import shutil

import pytest
from ffmpeg import FFmpeg

from support import FakeFFmpeg


@pytest.fixture
def ffmpeg(monkeypatch: pytest.MonkeyPatch) -> FakeFFmpeg:
    """Replace FFmpeg with a fake that the test can configure and inspect."""
    fake = FakeFFmpeg()
    monkeypatch.setattr(shutil, "which", lambda name: name)
    monkeypatch.setattr(FFmpeg, "execute", lambda command: fake.execute(command.arguments))
    return fake
