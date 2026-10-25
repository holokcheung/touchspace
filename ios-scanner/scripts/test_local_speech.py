#!/usr/bin/env python3
"""Run actual simulator -> local Whisper -> spoken map answer integration.

First build-for-testing with the TouchSpace scheme and start the backend with
local speech configured. The WAV fixture is synthesized speech, not a transcript.
"""
import argparse
import plistlib
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--derived-data', type=Path, default=Path('/tmp/touchspace-derived'))
parser.add_argument('--device', default='15676F37-1110-475D-897E-06E54FFEC2D1')
args = parser.parse_args()
products = args.derived_data / 'Build/Products'
sources = sorted(products.glob('TouchSpace_iphonesimulator*.xctestrun'))
if not sources:
    parser.error('Run xcodebuild build-for-testing with the selected derived data path first')
configuration = plistlib.loads(sources[-1].read_bytes())
targets = [target for group in configuration.get('TestConfigurations', []) for target in group.get('TestTargets', [])]
if not targets:
    targets = [configuration['TouchSpaceTests']]
for target in targets:
    target.setdefault('EnvironmentVariables', {})['TOUCHSPACE_SPEECH_INTEGRATION'] = '1'
# Keep __TESTROOT__ resolution in Products while enabling the opt-in test only here.
with tempfile.NamedTemporaryFile(dir=products, suffix='.xctestrun') as output:
    output.write(plistlib.dumps(configuration)); output.flush()
    subprocess.run(['xcodebuild', '-xctestrun', output.name, '-destination', f'platform=iOS Simulator,id={args.device}',
                    '-parallel-testing-enabled', 'NO', '-collect-test-diagnostics', 'never',
                    '-only-testing:TouchSpaceTests/ServerSpeechRecognitionIntegrationTests', 'test-without-building'], check=True)
