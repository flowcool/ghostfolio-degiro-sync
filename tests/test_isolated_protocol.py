"""Offline process boundaries for the disposable lab controller."""
import subprocess
import sys

import pytest

from scripts.isolated_acceptance import driver_lines


@pytest.mark.parametrize('program,expected', [
    ('print("ARM_BARRIER: cash"); print("QUIESCENCE_READY: cash")',
     ['ARM_BARRIER: cash', 'QUIESCENCE_READY: cash']),
    ('import os; os.write(1,b"ARM_"); os.write(1,b"BARRIER: cash\\n")',
     ['ARM_BARRIER: cash']),
])
def test_driver_protocol_preserves_complete_ordered_lines(program, expected):
    with subprocess.Popen([sys.executable, '-c', program], stdout=subprocess.PIPE) as process:
        assert list(driver_lines(process, timeout=5)) == expected
        assert process.wait(timeout=5) == 0


@pytest.mark.parametrize('program,message', [
    ('import time; time.sleep(10)', 'deadline'),
    ('import os; os.write(1,b"unfinished")', 'Incomplete'),
    ('print("x"*9000)', 'line budget'),
])
def test_driver_protocol_failure_is_bounded(program, message):
    process = subprocess.Popen([sys.executable, '-c', program], stdout=subprocess.PIPE)
    try:
        with pytest.raises(RuntimeError, match=message):
            list(driver_lines(process, timeout=.2 if message == 'deadline' else 5))
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        process.stdout.close()
