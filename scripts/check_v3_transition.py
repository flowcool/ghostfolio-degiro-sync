#!/usr/bin/env python3
"""Reproduce public V3 fixtures in a disposable network-disabled converter."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import uuid

import yaml


def run(arguments, timeout=30):
    result = subprocess.run(arguments, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('V3 reproduction command failed')
    return result.stdout


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, help='Existing inspected external converter Git checkout')
    args = parser.parse_args(argv)
    fixture = yaml.safe_load((Path(__file__).resolve().parents[1] /
        'tests/fixtures/degiro_v3_transition.yaml').read_text())
    provenance = fixture['provenance']
    pin = provenance['commit']
    paths = ['src', 'package.json', 'package-lock.json', 'tsconfig.json']
    source = str(Path(args.source).resolve())
    for name, key in ((provenance['converter_path'], 'converter_sha256'),
                      ('package-lock.json', 'package_lock_sha256')):
        content = run(['git', '-C', source, 'show', pin + ':' + name])
        if hashlib.sha256(content).hexdigest() != provenance[key]:
            raise RuntimeError('Pinned V3 source hash mismatch')
    archive = run(['git', '-C', source, 'archive', pin, '--', *paths])
    # Unique label/tag: never overwrite or remove a pre-existing operator image.
    image = 'degiro-v3-reproduction:' + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='degiro-v3-reproduction-') as temporary:
        root = Path(temporary)
        with tarfile.open(fileobj=io.BytesIO(archive)) as package:
            package.extractall(root, filter='data')
        cases = {name: case['input_csv'] for name, case in fixture['cases'].items()}
        (root / 'cases.json').write_text(json.dumps(cases))
        (root / 'src/v3Probe.ts').write_text('''import fs from 'node:fs';
import { DeGiroConverterV3 } from './converters/degiroConverterV3';
process.env.GHOSTFOLIO_ACCOUNT_ID = 'synthetic-csv-target';
delete process.env.GHOSTFOLIO_TAG_IDS;
console.log = () => {};
const security = {getSecurity: async (isin: string) => {
  if (isin !== 'US0378331005') throw new Error('Unexpected synthetic security');
  return {symbol: 'TEST'};
}};
const output = {};
for (const [name, input] of Object.entries(JSON.parse(fs.readFileSync('cases.json','utf8')))) {
  const converter = new DeGiroConverterV3(security as any);
  const result: any = await new Promise((resolve, reject) => converter.processFileContents(input as string, resolve, reject));
  output[name] = {meta: {version: result.meta.version}, activities: result.activities};
}
process.stdout.write(JSON.stringify(output));
''')
        (root / 'Dockerfile').write_text('FROM ' + provenance['runtime_image'] + '''
WORKDIR /work
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY src ./src
COPY tsconfig.json cases.json ./
CMD ["./node_modules/.bin/tsx", "src/v3Probe.ts"]
''')
        built = False
        finished = False
        cid = root / 'converter.cid'
        try:
            run(['docker', 'build', '-t', image, str(root)], timeout=300)
            built = True
            raw = run(['docker', 'run', '--rm', '--network', 'none', '--read-only',
                '--cidfile', str(cid),
                '--tmpfs', '/tmp:rw,nosuid,nodev,size=16m', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--user', '1000:1000',
                '-e', 'TZ=' + provenance['timezone'], image], timeout=30)
            finished = True
            output = json.loads(raw)
            expected = {name: case['output'] for name, case in fixture['cases'].items()}
            if output != expected:
                raise RuntimeError('Native V3 output differs from captured fixture')
            print('PASS pinned native V3: three public synthetic inputs match exact captured output')
        finally:
            # A killed Docker client need not stop its container. The private
            # cidfile identifies only the container created by this invocation.
            if not finished and cid.exists():
                identity = cid.read_text().strip()
                if not re.fullmatch(r'[0-9a-f]{64}', identity):
                    raise RuntimeError('Invalid owned V3 container identity')
                run(['docker', 'rm', '-f', identity])
            if built:
                run(['docker', 'image', 'rm', image])


if __name__ == '__main__':
    main()
