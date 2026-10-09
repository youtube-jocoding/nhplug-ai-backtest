#!/bin/sh
# Read-only recording helper. Never displays credentials or starts trading.
set -eu
cd "$(dirname "$0")"
if [ -n "${BACKTEST_PYTHON:-}" ]; then
  task_python="$BACKTEST_PYTHON"
elif python3 -c 'import sys; sys.exit(sys.version_info < (3,10))' 2>/dev/null; then
  task_python=python3
elif [ -x "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" ]; then
  task_python="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
else
  echo 'Python 3.10 이상을 설치하거나 BACKTEST_PYTHON에 실행 파일 경로를 지정하세요.' >&2
  exit 1
fi
"$task_python" -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10 이상 필요"'
case "${1:-check}" in
  check) "$task_python" -m unittest -v test_studio test_filming ;;
  replay) "$task_python" run.py --dataset datasets/nh-005930.json --provider replay --start 2026-09-14 --end 2026-09-23 --out runs/filming-replay.json ;;
  serve) exec "$task_python" server.py --port "${2:-8770}" ;;
  *) echo '사용법: sh film.sh [check|replay|serve [포트]]' >&2; exit 2 ;;
esac
