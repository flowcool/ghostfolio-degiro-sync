#!/usr/bin/env python3
"""Owned disposable Ghostfolio3.81.0 lab; never contacts an operator account."""
import argparse
import json
import os
from pathlib import Path
import secrets
import select
import subprocess
import tempfile
import time
import uuid

import yaml


GHOST_IMAGE = 'ghostfolio/ghostfolio:3.81.0@sha256:7c925671dba267cc2175195f064b42b9733f3ea170a21db488b7d2be3319e088'
POSTGRES_IMAGE = 'postgres:15-alpine@sha256:f7d23353e1b15400d22ebe31189f4d314b87a4c129cc400c8c2d8d4ca127bf81'
REDIS_IMAGE = 'redis:7-alpine@sha256:858f009f9709ce576febc734aa78b8f6d624b82571f9ddb6bda4377c833b3499'


def run(*args, input_text=None, timeout=60):
    result = subprocess.run(args, input=input_text, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Owned isolated command failed with code ' + str(result.returncode))
    return result.stdout


def compose_command(project, path):
    return ['docker', 'compose', '-p', project, '-f', str(path)]


def driver_lines(process, timeout=600):
    """Bound the whole lab protocol, including a driver that never reaches EOF."""
    deadline = time.monotonic() + timeout
    buffered = b''
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([process.stdout], [], [], remaining)[0]:
            raise RuntimeError('Owned acceptance driver exceeded protocol deadline')
        chunk = os.read(process.stdout.fileno(), 4096)
        if not chunk:
            if buffered:
                raise RuntimeError('Incomplete owned driver protocol line')
            return
        buffered += chunk
        if len(buffered) > 8192:
            raise RuntimeError('Owned driver protocol exceeds line budget')
        while b'\n' in buffered:
            line, buffered = buffered.split(b'\n', 1)
            yield line.decode('utf-8')


def acquire_barrier(sql_command, timeout=30):
    process = subprocess.Popen(sql_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True)
    try:
        process.stdin.write('SELECT pg_backend_pid();\nSELECT pg_advisory_lock(81005611);\n')
        process.stdin.flush()
        lines = driver_lines(process, timeout=timeout)
        identity = next(lines).strip()
        if not identity.isascii() or not identity.isdecimal() or len(identity) > 10:
            raise RuntimeError('Invalid owned barrier process identity')
        identity = int(identity)
        if not 0 < identity <= 2147483647:
            raise RuntimeError('Invalid owned barrier process identity')
        if next(lines).strip() != '':
            raise RuntimeError('Invalid owned barrier acquisition acknowledgement')
        return process, identity
    except BaseException as error:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
        if isinstance(error, (StopIteration, UnicodeDecodeError)):
            raise RuntimeError('Incomplete owned barrier response') from None
        raise


def main():
    if not __debug__:
        raise RuntimeError('Owned acceptance requires Python assertions enabled')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-image', required=True)
    args = parser.parse_args()
    project = 'degiro-c13-' + uuid.uuid4().hex[:10]
    worker = project + '-driver'
    with tempfile.TemporaryDirectory(prefix='degiro-c13-') as directory:
        directory = Path(directory)
        patch = '''
const fs = require('fs');
const source = fs.readFileSync('/ghostfolio/apps/api/main.js', 'utf8');
const old = 'async getAssetProfile({symbol:e}){return this.yahooFinanceDataEnhancerService.getAssetProfile(e)}';
if (source.split(old).length !== 2) throw new Error('Pinned quote delegation differs');
const replacement = 'async getAssetProfile({symbol:e}){if(e!=="TEST")return undefined;return {dataSource:"YAHOO",symbol:"TEST",currency:"USD",name:"Synthetic TEST"}}';
process.stdout.write(source.replace(old, replacement));
'''
        # Only the quote/profile boundary is doubled. Native import/account/DB
        # code and all financial validation remain byte-identical to the image.
        (directory / 'main.js').write_text(run('docker', 'run', '--rm', '--network=none',
            '--entrypoint', 'node', GHOST_IMAGE, '-e', patch))
        (directory / 'Dockerfile').write_text('FROM ' + GHOST_IMAGE + '\nCOPY main.js /ghostfolio/apps/api/main.js\n')
        image = project + ':profile-fixture'
        run('docker', 'build', '-t', image, str(directory), timeout=120)
        password = secrets.token_hex(24)
        services = {
            'postgres': {'image': POSTGRES_IMAGE, 'networks': ['lab'],
                'tmpfs': ['/var/lib/postgresql/data'],
                'environment': {'POSTGRES_DB': 'c13lab', 'POSTGRES_USER': 'c13lab', 'POSTGRES_PASSWORD': password},
                'healthcheck': {'test': ['CMD-SHELL', 'pg_isready -U c13lab -d c13lab'],
                    'interval': '1s', 'timeout': '3s', 'retries': 30}},
            'redis': {'image': REDIS_IMAGE, 'networks': ['lab']},
            'ghostfolio': {'image': image, 'networks': ['lab'],
                'depends_on': {'postgres': {'condition': 'service_healthy'}, 'redis': {'condition': 'service_started'}},
                'environment': {'DATABASE_URL': 'postgresql://c13lab:' + password + '@postgres:5432/c13lab',
                    'ACCESS_TOKEN_SALT': secrets.token_hex(32), 'JWT_SECRET_KEY': secrets.token_hex(32),
                    'NODE_ENV': 'production', 'REDIS_HOST': 'redis', 'REDIS_PORT': '6379'}}}
        compose = directory / 'compose.yaml'
        compose.write_text(yaml.safe_dump({'name': project, 'networks': {'lab': {'internal': True}}, 'services': services}))
        compose.chmod(0o600)
        command = compose_command(project, compose)
        barrier = None
        driver = None
        try:
            run(*command, 'up', '-d', timeout=120)
            postgres = run(*command, 'ps', '-q', 'postgres').strip()
            ghost = run(*command, 'ps', '-q', 'ghostfolio').strip()
            network = project + '_lab'
            network_info = json.loads(run('docker', 'network', 'inspect', network))[0]
            assert network_info['Internal'] is True
            for identity in (postgres, ghost):
                info = json.loads(run('docker', 'inspect', identity))[0]
                assert info['Config']['Labels']['com.docker.compose.project'] == project
                assert not info['HostConfig']['Binds'] and not info['HostConfig']['PortBindings']
            sql_command = ['docker', 'exec', '-i', postgres, 'psql', '-U', 'c13lab', '-d', 'c13lab', '-v', 'ON_ERROR_STOP=1', '-At']
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                try:
                    if run(*sql_command, input_text='SELECT count(*) FROM "Order";\nSELECT count(*) FROM "AccountBalance";\n').strip() == '0\n0':
                        break
                except RuntimeError:
                    pass
                time.sleep(.5)
            else:
                raise RuntimeError('Owned schema migration not ready')
            run(*sql_command, input_text='''
CREATE FUNCTION c13_block_owned_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.comment IN ('DEGIRO#123:FEE:999', 'DEGIRO#901:FEE:1002') THEN
   PERFORM pg_advisory_xact_lock(81005611);
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER c13_owned_delay BEFORE INSERT ON "Order"
FOR EACH ROW EXECUTE FUNCTION c13_block_owned_insert();
CREATE FUNCTION c13_block_owned_cash() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.value IN (42.42, 84.84) THEN
   PERFORM pg_advisory_xact_lock(81005611);
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER c13_owned_cash_delay BEFORE INSERT OR UPDATE ON "AccountBalance"
FOR EACH ROW EXECUTE FUNCTION c13_block_owned_cash();
''')

            def release_barrier(process):
                process.stdin.write('SELECT pg_advisory_unlock(81005611);\n\\q\n')
                process.stdin.flush()
                assert process.wait(timeout=10) == 0

            barrier, barrier_pid = acquire_barrier(sql_command)
            run('docker', 'run', '-d', '--name', worker, '--network', network,
                '--read-only', '--tmpfs', '/tmp:rw,nosuid,nodev,size=32m', '--cap-drop=ALL',
                '--security-opt=no-new-privileges',
                '-v', str(Path('scripts/acceptance_driver.py').resolve()) + ':/lab/driver.py:ro',
                '-v', str(Path('tests/fixtures/degiro_contract.yaml').resolve()) + ':/lab/fixture.yaml:ro',
                '-v', str(Path('tests/fixtures/degiro_v3_transition.yaml').resolve()) + ':/lab/v3.yaml:ro',
                args.runtime_image, 'python', '-c', 'import time; time.sleep(1800)')
            driver = subprocess.Popen(['docker', 'exec', '-i', '-e', 'DEGIRO_ISOLATED_ACCEPTANCE=synthetic-c13',
                worker, 'python', '/lab/driver.py'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)
            released = False
            quiescent = 0
            cash_released = False
            for line in driver_lines(driver):
                print(line.strip(), flush=True)
                if line.startswith('ARM_BARRIER:'):
                    assert barrier.poll() is not None
                    barrier, barrier_pid = acquire_barrier(sql_command)
                    driver.stdin.write('armed\n')
                    driver.stdin.flush()
                elif line.startswith(('BARRIER_READY:', 'CASH_RELEASE_READY:', 'QUIESCENCE_READY:')):
                    blocked = run(*sql_command, input_text="SELECT count(*) FROM pg_stat_activity WHERE wait_event = 'advisory';\n")
                    assert int(blocked.strip()) >= 1
                    if line.startswith('QUIESCENCE_READY:'):
                        # Stop only this UUID-owned sole app before terminating
                        # its DB work. Client disconnection alone is not cancellation.
                        info = json.loads(run('docker', 'inspect', ghost))[0]
                        assert info['Config']['Labels']['com.docker.compose.project'] == project
                        run('docker', 'stop', '-t', '10', ghost, timeout=30)
                        assert json.loads(run('docker', 'inspect', ghost))[0]['State']['Running'] is False
                        run(*sql_command, input_text=f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid() AND pid <> {barrier_pid};\n")
                        deadline = time.monotonic() + 10
                        while time.monotonic() < deadline:
                            remaining = run(*sql_command, input_text=f"SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid() AND pid <> {barrier_pid};\n")
                            if remaining.strip() == '0':
                                break
                            time.sleep(.2)
                        else:
                            raise RuntimeError('Owned database work did not become quiescent')
                        release_barrier(barrier)
                        remaining = run(*sql_command, input_text="SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid();\n")
                        assert remaining.strip() == '0'
                        run('docker', 'start', ghost)
                        driver.stdin.write('quiescent\n')
                        quiescent += 1
                    else:
                        release_barrier(barrier)
                        driver.stdin.write('release\n')
                        if line.startswith('BARRIER_READY:'):
                            released = True
                        else:
                            cash_released = True
                    driver.stdin.flush()
            assert driver.wait(timeout=30) == 0 and released and cash_released and quiescent == 2
            print('PASS owned internal network, distinct temporary database, no published ports/production credentials; native INSERT/cash barriers and two independent quiescence proofs verified', flush=True)
        finally:
            if driver is not None and driver.poll() is None:
                driver.terminate()
                driver.wait(timeout=10)
            if barrier is not None and barrier.poll() is None:
                barrier.terminate()
                barrier.wait(timeout=10)
            subprocess.run(['docker', 'rm', '-f', worker], capture_output=True, timeout=20)
            run(*command, 'down', timeout=60)
            run('docker', 'image', 'rm', image, timeout=30)
            print('Owned lab containers/network removed', flush=True)


if __name__ == '__main__':
    main()
