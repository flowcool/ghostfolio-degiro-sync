"""Detect crash-durability gaps using synthetic records and real local files."""
import importlib.util
import os
from pathlib import Path
import stat

import pytest
import yaml

from scripts import lab_cleanup

SPEC = importlib.util.spec_from_file_location('credential_delivery_durability',
    Path(__file__).resolve().parents[1] / 'scripts/check_credential_delivery.py')
delivery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(delivery)


@pytest.mark.parametrize('writer', [delivery, lab_cleanup], ids=['credentials', 'cleanup'])
@pytest.mark.parametrize('failure', [None, 'file-sync', 'replace', 'directory-open', 'directory-sync'])
def test_replacement_is_durable_before_success_and_failures_propagate(tmp_path, monkeypatch,
                                                                     writer, failure):
    path = tmp_path / 'ownership.yaml'

    def save(resources):
        if writer is delivery:
            writer.save_record(path, 'synthetic', resources)
        else:
            writer.save_record({'record': path, 'project': 'synthetic', 'resources': resources})

    save({'old': 'a' * 64})
    before = path.read_bytes()
    events = []
    descriptors = []
    real_open, real_fsync, real_replace, real_close = os.open, os.fsync, os.replace, os.close

    def record_open(target, flags, *args, **kwargs):
        if Path(target) == tmp_path:
            events.append('directory-open')
            if failure == 'directory-open':
                raise OSError('synthetic directory-open failure')
            descriptor = real_open(target, flags, *args, **kwargs)
            assert stat.S_ISDIR(os.fstat(descriptor).st_mode)
            descriptors.append(descriptor)
            return descriptor
        return real_open(target, flags, *args, **kwargs)

    def record_sync(descriptor):
        event = 'directory-sync' if stat.S_ISDIR(os.fstat(descriptor).st_mode) else 'file-sync'
        events.append(event)
        if failure == event:
            raise OSError('synthetic ' + event + ' failure')
        real_fsync(descriptor)

    def record_replace(source, target):
        events.append('replace')
        if failure == 'replace':
            raise OSError('synthetic replace failure')
        real_replace(source, target)

    def record_close(descriptor):
        if descriptor in descriptors:
            events.append('directory-close')
        real_close(descriptor)

    monkeypatch.setattr(writer.os, 'open', record_open)
    monkeypatch.setattr(writer.os, 'fsync', record_sync)
    monkeypatch.setattr(writer.os, 'replace', record_replace)
    monkeypatch.setattr(writer.os, 'close', record_close)
    if failure:
        with pytest.raises(OSError, match='synthetic ' + failure + ' failure'):
            save({'new': 'b' * 64})
    else:
        save({'new': 'b' * 64})

    expected = ['file-sync', 'replace', 'directory-open', 'directory-sync', 'directory-close']
    if failure:
        expected = expected[:expected.index(failure) + 1]
        if failure == 'directory-sync':
            expected.append('directory-close')
    assert events == expected
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    if failure in ('file-sync', 'replace'):
        assert path.read_bytes() == before
    else:
        # After replacement a failed directory sync means uncertain durability,
        # not restoration of the old record; the new YAML is already visible.
        body = yaml.safe_load(path.read_text())
        assert body['containers' if writer is delivery else 'resources'] == {'new': 'b' * 64}
    assert path.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.iterdir()) == [path]
