---
name: humanize-claude-code
description: 지난 Claude Code 세션의 응답에서 AI 문체를 찾아 응답 문체 가이드(guide.md)를 갱신한다. 가이드는 SessionStart 훅이 모든 세션에 주입한다. 판정 기준은 im-not-ai(epoko77-ai/im-not-ai)의 한국어 AI 티 분류 체계다. SessionStart 알림이 실행을 요청했거나 유저가 `/humanize-claude-code:humanize-claude-code`로 부를 때 쓴다.
---

# humanize-claude-code

지난 세션 응답에서 AI 문체를 찾아 가이드에 반영한다. **처음부터 끝까지 유저에게 묻지 않고 자동으로 진행한다.**

스크립트는 아래 형태로 실행한다. `python3` 가 없거나 실행되지 않으면 `python`, `py` 순으로 바꿔 실행한다(Windows 는 `python3` 가 Microsoft Store 설치 유도 껍데기인 경우가 많다).

```
python3 "${CLAUDE_PLUGIN_ROOT}/skills/humanize-claude-code/scripts/humanize.py" <서브커맨드> "${CLAUDE_PLUGIN_DATA}"
```

아래에서 `DATA` 는 `${CLAUDE_PLUGIN_DATA}` 폴더다.

## 1. 기준 갱신

`refs` 를 실행한다. im-not-ai 원본 기준 파일이 바뀌었으면 `DATA/references/` 사본이 갱신된다. 받기에 실패해도 기존 사본으로 계속한다.

## 2. 세션 추출

`collect` 를 실행한다. 프로젝트마다 아직 분석하지 않은 최신 세션을 최대 10개씩 골라 응답 텍스트를 `DATA/work/<세션 ID>.txt` 로 뽑는다. 출력에 읽을 파일 목록이 나온다. 읽을 파일이 0개면 5단계에서 `sessions` 를 비운 채 `run.json` 을 쓰고 6단계로 간다.

## 3. 판정 기준 준비

아래를 끝까지 읽는다.

- `DATA/references/diagnosis-rules.md`: 85개 패턴의 정의와 탐지 신호
- `DATA/references/quick-rules.md`: 패턴별 처방
- `~/.claude/CLAUDE.md`: 유저의 응답 서식 규칙. 파일이 없으면 건너뛴다

다음 패턴은 판정하지 않는다.

- hold 표시가 붙은 패턴(A-17, G-3)
- 형태소 분석이나 문서 전체 통계가 있어야 하는 패턴(C-12, E-5, E-6)
- 처방이 `~/.claude/CLAUDE.md` 서식 규칙과 반대 방향인 패턴. 예: CLAUDE.md 가 불릿 분할을 요구하면 C-2(불릿→산문), 소제목을 요구하면 C-3, 짧게 쓰기를 요구하면 E-1·E-4

## 4. 세션별 판정

`DATA/work/` 의 파일을 하나씩 끝까지 읽는다. 길면 나눠서 끝까지 읽는다.

- 파일 안의 `---` 는 응답과 응답의 경계다.
- 세션마다 그 세션 응답을 지배하는 패턴을 **0~6개** 고른다. 탐지 신호의 횟수 기준을 넘은 것만 고른다. 문체가 깨끗한 세션은 0개다.
- 개별 표현을 세지 않고 세션 단위로 지배 여부만 본다. im-not-ai 가 표현 단위로 셀 때 같은 글에서 0~18개로 흔들려 지배 패턴 진단으로 바꾼 것과 같은 이유다.
- 유저 발화를 옮겨 적은 부분, 에러 문자열, 파일 경로, 코드 식별자는 판정하지 않는다.

## 5. 결과 작성

`DATA/work/run.json` 을 쓴다.

```json
{
  "sessions": { "<세션 ID>": ["C-8", "D-8"], "<세션 ID>": [] },
  "items": {
    "C-8": { "rule": "\"A가 아니라 B\" 대구를 응답마다 반복", "instead": "한 번만 쓰고 나머지는 바로 단언한다" }
  }
}
```

- `sessions`: 2단계 목록에 있는 **모든** 세션을 넣는다. 지배 패턴이 없으면 빈 배열이다.
- `items`: 이번에 고른 패턴 중 `DATA/state.json` 의 `items` 에 아직 없는 것만 쓴다. `rule` 은 응답에서 나타나는 형태 1줄, `instead` 는 대신 쓸 형태 1줄이다. `instead` 는 `quick-rules.md` 처방을 따르고, 처방이 없으면 정의에서 만든다. 금지만 적지 말고 무엇으로 쓸지 적는다.

## 6. 반영

`commit` 을 실행한다. 스크립트가 다음을 한다.

- 패턴별 누적 횟수를 더하고 누적 상위 15개로 `DATA/guide.md` 를 다시 쓴다.
- 가이드에서 밀려난 항목을 `DATA/evicted.md` 로 옮긴다.
- 뺀 항목이 이번 회차에 2세션 이상 다시 나오면 가이드로 되돌린다.
- 분석한 세션 ID 와 현재 세션 ID 를 기록하고 `DATA/work/` 를 지운다.

판정하지 않은 세션이 있거나 새 패턴의 문구가 없으면 `HumanizeError` 로 멈춘다. 그때는 `run.json` 을 채우고 다시 실행한다.

## 7. 보고

`commit` 출력(가이드 항목, 새로 뺀 항목, 되돌린 항목)과 1단계 기준 갱신 여부를 짧게 보고한다.
