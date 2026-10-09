# 프롬프트를 받은 Codex의 실행 절차

## 1. 내려받기
사용자 작업 폴더의 빈 하위 폴더에 받는다. 기존 설치가 있으면 변경을 보존한다. 기존 자동매매 저장소를 덮어쓰거나 실행하지 않는다.
- git clone https://github.com/youtube-jocoding/nhplug-ai-backtest
- git 없음: https://github.com/youtube-jocoding/nhplug-ai-backtest/archive/refs/heads/main.zip 을 내려받아 새 폴더에 안전하게 해제.

## 2. 실행 환경
Python 3.10 이상을 찾는다. macOS 기본 python3는 3.9일 수 있으므로 확인한다.
설치된 정상 Python이나 Codex 작업용 Python을 우선 사용한다. 없으면 공식 Python 배포판 또는 설치된 패키지 관리자로 설치를 도와준다. 관리자 승인·설치 UI만 사용자에게 요청한다. 터미널 입력·파일 편집을 요구하지 않는다. 권한·네트워크가 없으면 명확히 멈춘다.
선택한 Python으로 bootstrap.py를 실행한다. .venv 생성·테스트가 통과해야 한다. 별도 Python 패키지는 필요 없다.

ai_provider.CodexProvider가 선택한 CLI의 --version, exec --help, login status를 확인한다. 깨진 PATH의 codex만 보고 포기하지 않는다.
정상 CLI가 없으면 https://developers.openai.com/codex/cli 공식 안내에 따라 설치한다. npm이 있으면 npm install -g @openai/codex를 사용할 수 있다.
로그인이 필요하면 선택된 CLI로 login을 실행하고 사용자에게 브라우저 인증만 요청한다. 비밀번호·토큰을 채팅에 요구하지 않는다. 앱 로그인과 CLI 로그인은 실제 상태로 확인한다.
--ignore-user-config, --output-schema, --ephemeral, --sandbox read-only를 지원하지 않는 버전은 업데이트를 안내한다. 보안을 해제하는 옵션으로 우회하지 않는다.
curl이 없으면 설치한다. NH는 8443 포트가 필요하므로 로컬 PC에서 진행한다. 네트워크 차단을 우회하지 않는다.

## 3. 설정 화면
.venv/bin/python setup.py --open (Windows는 .venv\\Scripts\\python.exe)으로 지속 실행한다.
출력된 10분 1회용 링크를 사용자에게 열어준다. API 키가 아니라 로컬 화면 접근용 링크다.
같은 브라우저에서 계속 사용한다. 포트 사용 중이면 앱이 빈 포트를 선택한다. 다른 앱을 종료하지 않는다.

## 4. 사용자 입력
로컬 화면에서 NH 키 입력 → 저장하고 연결 확인 → AI 이용량 안내 동의 → AI 백테스트 시작.
키가 없으면 공식 포털 이용 신청·키 발급을 안내하고 기다린다. 대신 약관 동의·키 발급을 하지 않는다.
앱이 과거 시세 조회 → 실제 AI 8일 판단 → 가상 계산을 수행한다. 기존 동일 입력의 AI 기록은 재사용한다.
실패 시 오류 상태를 유지한다. 샘플로 대체하거나 반복 재시도하지 않는다.

## 5. 결과
완료 후 결과 화면 열기 → 백테스트 실행. 저장된 실제 판단을 재생한다.
날짜별 판단·가상 체결·평가손익을 확인하고 결과 주소를 알려준다.
실제 주문이 없고, 현재 AI의 과거 재분석이며 결과가 영상과 다를 수 있다고 설명한다. 8일은 시연이지 수익성 입증 표본이 아니다.
추가 자동매매 예약이나 GitHub 업로드를 하지 않는다.
