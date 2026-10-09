"""Portable setup, including timezone data on Windows. Creates a private project venv."""
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
        venv.EnvBuilder(with_pip=True).create(env)
    zone = subprocess.run([str(binary), '-c', "from zoneinfo import ZoneInfo; ZoneInfo('Asia/Seoul')"], capture_output=True)
    if zone.returncode:
        subprocess.run([str(binary), '-m', 'ensurepip', '--upgrade'], check=True)
        subprocess.run([str(binary), '-m', 'pip', 'install', 'tzdata'], check=True)
    subprocess.run([str(binary), '-X', 'utf8', '-m', 'unittest', 'discover', '-v'], cwd=ROOT, check=True)
    from ai_provider import CodexProvider
    provider = CodexProvider(ROOT / 'cache', True)
    working = False
    if provider.binary:
        try:
            version = subprocess.run([provider.binary, '--version'], capture_output=True, timeout=10)
            help_result = subprocess.run([provider.binary, 'exec', '--help'], capture_output=True, timeout=10, text=True, encoding='utf-8')
            login = subprocess.run([provider.binary, 'login', 'status'], capture_output=True, timeout=10)
            working = version.returncode == login.returncode == help_result.returncode == 0 and all(flag in help_result.stdout for flag in ('--ignore-user-config', '--output-schema', '--ephemeral', '--sandbox'))
        except (OSError, subprocess.TimeoutExpired):
            pass
    print(json.dumps(dict(python=str(binary), codex_available=working,
                          curl_available=bool(shutil.which('curl')),
                          next='Run the venv Python with setup.py --open. User enters keys only in browser.'), ensure_ascii=False))

    if not working or not shutil.which('curl'):
        raise SystemExit('Codex CLI 로그인·필수 기능 또는 curl 확인이 필요합니다. Codex가 설치와 로그인을 도와야 합니다.')

if __name__ == '__main__':
    main()
