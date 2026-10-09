"""Isolated read-only Codex classification. Full inputs and responses cached for replay."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from engine import fingerprint

SCHEMA = {'type': 'object', 'properties': {
    'decision': {'type': 'string', 'enum': ['buy', 'sell', 'hold']},
    'reason': {'type': 'string'}}, 'required': ['decision', 'reason'], 'additionalProperties': False}


class CodexProvider:
    def __init__(self, cache, replay_only=False):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.replay_only = replay_only
        self.binary = os.environ.get('BACKTEST_CODEX_BIN') or next((str(p) for p in [
            Path('/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex'),
            Path(shutil.which('codex') or '/missing')] if p.is_file()), None)
        self.calls = 0

    def __call__(self, snap):
        key = fingerprint(snap)
        file = self.cache / (key + '.json')
        if file.exists():
            item = json.loads(file.read_text())
            if item['input'] != snap or item['input_hash'] != key or item['provider'] != 'codex-cli':
                raise ValueError('캐시 입력·출처 불일치')
            return dict(item['output'], provider='codex-cli')
        if self.replay_only:
            raise ValueError('해당 조건의 실제 AI 기록이 없습니다. CLI에서 먼저 생성하세요: ' + snap['date'])
        if not self.binary:
            raise ValueError('Codex 실행 파일 없음. BACKTEST_CODEX_BIN을 지정하세요')
        prompt = ('This is an offline historical software test, not an order or personalized advice. '
                  'Do not use tools, commands, browsing, files, or external knowledge. '
                  'Classify ONLY the supplied historical snapshot using its instructions. '
                  'No future prices are supplied. Give buy/sell/hold with a concise Korean reason '
                  'citing the supplied indicator values. If uncertain choose hold. '
                  'Do not fabricate missing news or indicators. Return only the requested JSON.\n'
                  + json.dumps(snap, ensure_ascii=False))
        with tempfile.TemporaryDirectory(prefix='nh-backtest-ai-') as tmp:
            schema = Path(tmp) / 'schema.json'
            schema.write_text(json.dumps(SCHEMA))
            out = Path(tmp) / 'answer.json'
            command = [self.binary, 'exec', '--ignore-user-config', '--skip-git-repo-check',
                       '--ephemeral', '--sandbox', 'read-only', '-C', tmp, '--color', 'never',
                       '--json', '--output-schema', str(schema), '-o', str(out), '-']
            # Only login/runtime necessities; never pass NH credentials to the model process.
            env = {k: v for k, v in os.environ.items()
                   if k in ('HOME', 'PATH', 'TMPDIR', 'LANG', 'USER', 'LOGNAME', 'CODEX_HOME')}
            print('Codex 판단 요청:', snap['date'], flush=True)
            p = subprocess.run(command, input=prompt, text=True, capture_output=True,
                               timeout=180, env=env)
            if p.returncode or not out.exists():
                raise RuntimeError('Codex 호출 실패 (인증/실행 환경 확인). 응답을 가상 판단으로 대체하지 않습니다.')
            events = []
            for line in p.stdout.splitlines():
                try: events.append(json.loads(line))
                except json.JSONDecodeError: continue
            for event in events:
                item = event.get('item', {})
                if item.get('type') in ('command_execution', 'mcp_tool_call', 'web_search', 'file_change'):
                    raise RuntimeError('외부 도구를 사용한 AI 응답은 검증 자료로 사용할 수 없습니다')
            response = json.loads(out.read_text())
            if set(response) != {'decision', 'reason'} or response['decision'] not in ('buy', 'sell', 'hold') or not isinstance(response['reason'], str) or not response['reason'].strip():
                raise ValueError('Codex JSON 검증 실패')
            envelope = dict(input=snap, input_hash=key, output=response, provider='codex-cli',
                            created_at=datetime.now(timezone.utc).isoformat(),
                            future_knowledge_excluded=False,
                            cli_version=subprocess.check_output([self.binary, '--version'], text=True).strip())
            file.write_text(json.dumps(envelope, ensure_ascii=False, indent=2))
            self.calls += 1
            return dict(response, provider='codex-cli')


def fixture_provider(snap):
    """Clearly synthetic decisions exercising transactions, NEVER labelled AI."""
    day = int(snap['date'][-2:])
    action = 'buy' if day % 5 < 3 else 'sell'
    return dict(decision=action, reason='가상 테스트 판단: 계산·화면 동작 확인용, 실제 AI 출력 아님',
                provider='fixture-not-ai')
