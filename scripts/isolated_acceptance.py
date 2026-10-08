#!/usr/bin/env python3
"""Owned disposable Ghostfolio3.81.0 lab; never contacts an operator account."""
import argparse
import json
from pathlib import Path
import secrets
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


def main():
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
        command = ['docker', 'compose', '-f', str(compose)]
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
                    if run(*sql_command, input_text='SELECT count(*) FROM "Order";\n').strip() == '0':
                        break
                except RuntimeError:
                    pass
                time.sleep(.5)
            else:
                raise RuntimeError('Owned schema migration not ready')
            run(*sql_command, input_text='''
CREATE FUNCTION c13_block_owned_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.comment = 'DEGIRO#123:FEE:999' THEN
   PERFORM pg_advisory_xact_lock(81005611);
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER c13_owned_delay BEFORE INSERT ON "Order"
FOR EACH ROW EXECUTE FUNCTION c13_block_owned_insert();
''')
            barrier = subprocess.Popen(sql_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)
            barrier.stdin.write('SELECT pg_advisory_lock(81005611);\n')
            barrier.stdin.flush()
            assert barrier.stdout.readline().strip() == ''
            run('docker', 'run', '-d', '--name', worker, '--network', network,
                '--read-only', '--tmpfs', '/tmp:rw,nosuid,nodev,size=32m', '--cap-drop=ALL',
                '--security-opt=no-new-privileges',
                '-v', str(Path('scripts/acceptance_driver.py').resolve()) + ':/lab/driver.py:ro',
                '-v', str(Path('tests/fixtures/degiro_contract.yaml').resolve()) + ':/lab/fixture.yaml:ro',
                args.runtime_image, 'python', '-c', 'import time; time.sleep(1800)')
            driver = subprocess.Popen(['docker', 'exec', '-i', '-e', 'DEGIRO_ISOLATED_ACCEPTANCE=synthetic-c13',
                worker, 'python', '/lab/driver.py'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)
            released = False
            for line in driver.stdout:
                print(line.strip(), flush=True)
                if line.startswith('BARRIER_READY:'):
                    blocked = run(*sql_command, input_text="SELECT count(*) FROM pg_stat_activity WHERE wait_event = 'advisory';\n")
                    assert int(blocked.strip()) >= 1
                    barrier.stdin.write('SELECT pg_advisory_unlock(81005611);\n\\q\n')
                    barrier.stdin.flush()
                    barrier.wait(timeout=10)
                    driver.stdin.write('release\n')
                    driver.stdin.flush()
                    released = True
            assert driver.wait(timeout=30) == 0 and released
            print('PASS owned internal network, distinct temporary database, no published ports/production credentials; native delayed INSERT barrier verified', flush=True)
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
