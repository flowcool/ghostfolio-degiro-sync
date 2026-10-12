"""Every runtime COPY must survive the intentionally explicit build allowlist."""

from pathlib import Path
import shlex


def test_runtime_copy_sources_are_included_in_restricted_context():
    root = Path(__file__).resolve().parents[1]
    rules = (root / '.dockerignore').read_text().splitlines()
    assert '**' in rules
    for line in (root / 'Dockerfile').read_text().splitlines():
        if not line.startswith('COPY '):
            continue
        for source in shlex.split(line)[1:-1]:
            path = root / source
            assert path.exists(), source
            if path.is_dir():
                assert '!' + source in rules, source
                assert '!' + source + '**' in rules, source
            else:
                assert '!' + source in rules, source
            for parent in Path(source).parents:
                if str(parent) != '.':
                    assert '!' + str(parent) + '/' in rules, source
