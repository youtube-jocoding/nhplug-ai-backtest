"""Zero third-party Python dependencies. Creates a private project venv."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent


def main():
    if sys.version_info < (3, 10):
        raise SystemExit('Python 3.10 이상 필요. Codex가 정상 Python 경로를 찾아 다시 실행해야 합니다.')
    env = ROOT / '.venv'
    binary = env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not binary.exists():
        venv.EnvBuilder(with_pip=False).create(env)
    subprocess.run([str(binary), '-m', 'unittest', 'discover', '-v'], cwd=ROOT, check=True)
    from ai_provider import CodexProvider
    provider = CodexProvider(ROOT / 'cache', True)
    working = False
    if provider.binary:
        try:
            working = subprocess.run([provider.binary, '--version'], capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass
    print(json.dumps(dict(python=str(binary), codex_available=working,
                          curl_available=bool(shutil.which('curl')),
                          next='Run the venv Python with setup.py --open. User enters keys only in browser.'), ensure_ascii=False))


if __name__ == '__main__':
    main()
