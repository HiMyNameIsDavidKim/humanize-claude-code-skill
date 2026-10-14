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
- `DATA/references/rewriting-playbook.md`: 윤문 대원칙과 카테고리별 before→after 예시
- `~/.claude/CLAUDE.md`: 유저의 응답 서식 규칙. 파일이 없으면 건너뛴다

`DATA/references/ai-tell-taxonomy.md`(분류 체계 원본, 약 3만 토큰)는 여기서 통째로 읽지 않는다. 5단계에서 문구를 쓸 패턴의 절만 읽는다.

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
    "C-8": {
      "rule": "\"A가 아니라 B\" 대구를 응답마다 반복",
      "instead": "한 번만 쓰고 나머지는 바로 단언한다",
      "example": "\"원인은 캐시가 아니라 락입니다\" → \"락이 원인입니다\""
    }
  }
}
```

- `sessions`: 2단계 목록에 있는 **모든** 세션을 넣는다. 지배 패턴이 없으면 빈 배열이다.
- `items`: 아래 패턴의 문구를 쓴다. 여기 쓴 문구는 `state.json` 의 기존 문구를 덮어쓴다.
  - 이번에 고른 패턴 중 `DATA/state.json` 의 `items` 에 아직 없는 것
  - 이번에 고른 패턴이나 `state.json` 의 `guide` 에 있는 패턴 중 `items` 에 `example` 이 없는 것(기준 보강 전에 쓴 문구)

문구는 이 순서로 쓴다.

1. `ai-tell-taxonomy.md` 에서 `### <ID>.` 로 시작하는 절을 찾아 다음 `##`·`###` 머리 전까지 끝까지 읽는다. 처방, 허가 조건(보존해야 하는 경우), 주입 금지 경고를 확인한다.
2. `rule` 은 응답에서 나타나는 형태 1줄로 쓴다.
3. `instead` 는 대신 쓸 형태 1줄로 쓴다. taxonomy 절의 처방을 따르고 금지만 적지 말고 무엇으로 쓸지 적는다. 그 형태가 다른 AI 티를 새로 만들면 안 된다(대구·"결국"·"~하는 이유다"·당위 종결·연결어미 뒤 쉼표 등 taxonomy 가 주입 금지로 적은 것). playbook 대원칙의 빼기 전용을 따른다.
4. `example` 은 `"원문" → "고친 문장"` 1줄이다. 원문은 이번 회차 세션 응답에서 그 패턴이 나온 실제 문장을 짧게 옮기고, 고친 문장은 `instead` 대로 고친 것이다. 이번 회차 세션에 그 패턴이 없으면 taxonomy·playbook 예문으로 만든다. 지시만으로는 구조 패턴이 바뀌지 않아서 예시를 붙인다(playbook C-8·D-8 실측).

## 6. 반영

`commit` 을 실행한다. 스크립트가 다음을 한다.

- 패턴별 누적 횟수를 더하고 누적 상위 15개로 `DATA/guide.md` 를 다시 쓴다.
- 가이드에서 밀려난 항목을 `DATA/evicted.md` 로 옮긴다.
- 뺀 항목이 이번 회차에 2세션 이상 다시 나오면 가이드로 되돌린다.
- 분석한 세션 ID 와 현재 세션 ID 를 기록하고 `DATA/work/` 를 지운다.

판정하지 않은 세션이 있거나, 새 패턴의 문구가 없거나, 가이드 항목에 `example` 이 없으면 `HumanizeError` 로 멈춘다. 그때는 `run.json` 을 채우고 다시 실행한다.

## 7. 보고

`commit` 출력(가이드 항목, 새로 뺀 항목, 되돌린 항목)과 1단계 기준 갱신 여부를 짧게 보고한다.
