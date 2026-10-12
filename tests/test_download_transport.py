"""Binary download options reject non-HTTPS before any external access."""

from pathlib import Path
import shlex
import shutil
import subprocess

import pytest


def download_options():
    dockerfile = (Path(__file__).resolve().parents[1] / 'Dockerfile').read_text()
    commands = [shlex.split(line.strip().removeprefix('&& ').removesuffix('\\'))
                for line in dockerfile.splitlines() if line.strip().startswith('&& curl ')]
    assert len(commands) == 2
    return [command[1:command.index(next(arg for arg in command if arg.startswith('https://')))]
            for command in commands]


@pytest.mark.parametrize('index', [0, 1])
def test_binary_download_refuses_local_file_with_runtime_options(tmp_path, index):
    executable = shutil.which('curl')
    if executable is None:
        pytest.skip('curl required for native transport-option regression')
    options = download_options()[index]
    # Do not follow Dockerfile output-file options in the offline regression.
    options = [option for option in options if option not in ('-fsSLO', '-fsSL')]
    source = tmp_path / 'synthetic-artifact'
    source.write_text('SYNTHETIC-DOWNLOAD-SENTINEL')
    result = subprocess.run([executable, *options, '--silent', '--show-error', source.as_uri()],
                            capture_output=True, text=True, timeout=5, check=False)
    assert result.returncode != 0
    assert 'SYNTHETIC-DOWNLOAD-SENTINEL' not in result.stdout + result.stderr
    assert options[options.index('--proto') + 1] == '=https'
    assert options[options.index('--proto-redir') + 1] == '=https'
    assert '--tlsv1.2' in options
