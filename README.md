# humanize-claude-code

Claude Code 가 한국어로 답할 때 나오는 AI 문체를 줄이는 플러그인입니다.

지난 세션의 응답을 읽어 자주 나온 AI 문체를 가이드로 만들고, 새 세션을 시작할 때마다 그 가이드를 자동으로 넣습니다. 일주일마다 새로 쌓인 세션을 다시 분석해 가이드를 고칩니다.

AI 문체 판정 기준은 [im-not-ai](https://github.com/epoko77-ai/im-not-ai)의 한국어 AI 티 분류 체계(85개 패턴)를 씁니다.

## 설치

```
/plugin marketplace add HiMyNameIsDavidKim/humanize-claude-code-skill
/plugin install humanize-claude-code
```

설치 뒤 새 세션을 열면 브라우저에 "응답 문체 분석이 필요합니다" 페이지가 뜹니다. 그때 아래 명령으로 첫 분석을 돌립니다.

```
/humanize-claude-code:humanize-claude-code
```

### 요구 사항

| 항목 | 내용 |
|---|---|
| Python | 3.8 이상. 표준 라이브러리만 씁니다 |
| macOS | 기본 `python3` 로 동작합니다 |
| Windows | [Git for Windows](https://git-scm.com/downloads/win)(Git Bash)가 있어야 합니다. 훅 명령이 bash 로 실행되기 때문입니다. Python 은 `python3`·`python`·`py` 중 실제로 실행되는 것을 골라 씁니다 |

## 동작 방식

### 세션 시작 (훅)

- 가이드(`guide.md`)가 있으면 세션 맥락에 넣습니다. 대화를 압축한 뒤에도 다시 넣습니다.
- 마지막 분석 후 7일이 지났고 아직 분석하지 않은 세션이 있으면, 새 세션을 열 때 브라우저로 알림 페이지를 띄웁니다. VS Code 확장은 훅의 알림 메시지를 화면에 그리지 않아서 브라우저를 씁니다.

### 분석 (스킬)

1. im-not-ai 원본 기준 파일이 바뀌었는지 확인하고, 바뀌었으면 받아 둡니다.
2. 프로젝트마다 아직 분석하지 않은 최신 세션을 최대 10개씩 고르고, Claude 응답 텍스트만 뽑습니다. 도구 호출·도구 결과·thinking·코드 블록은 뺍니다.
3. 세션마다 응답을 지배하는 AI 문체 패턴을 0~6개 고릅니다.
4. 새로 나온 패턴은 im-not-ai 분류 체계의 해당 절을 읽고 가이드 문구를 씁니다. 항목마다 세션 응답의 실제 문장을 고친 예시를 붙입니다.
5. 패턴별로 나온 세션 수를 누적하고, 상위 15개로 가이드를 다시 씁니다.
6. 가이드에서 밀려난 패턴은 `evicted.md` 에 기록합니다. 다음 분석에서 그 패턴이 2세션 이상 다시 나오면 가이드로 되돌립니다.

분석한 세션 ID 는 기록해 두고 다시 분석하지 않습니다. 분석을 돌린 세션도 함께 기록해서 다음 분석 대상에서 빠집니다.

가이드는 전역 하나입니다. 모든 프로젝트의 세션을 모아 분석하고, 모든 프로젝트 세션에 같은 가이드를 넣습니다.

## 파일

```
humanize-claude-code-skill/
├── .claude-plugin/
│   ├── plugin.json
│   └── marketplace.json
├── hooks/hooks.json                  ← SessionStart 훅
└── skills/humanize-claude-code/
    ├── SKILL.md                      ← 분석 절차
    ├── scripts/humanize.py           ← 세션 추출·누적·가이드 생성·훅
    └── references/                   ← im-not-ai 기준 파일 사본과 라이선스
```

상태와 결과는 플러그인 데이터 폴더(`~/.claude/plugins/data/<플러그인 ID>/`)에 둡니다. 플러그인을 업데이트해도 유지되고, 제거하면 함께 지워집니다.

| 파일 | 내용 |
|---|---|
| `guide.md` | 세션에 주입되는 가이드. 최대 15개 |
| `evicted.md` | 가이드에서 뺀 패턴과 재발 기록 |
| `state.json` | 마지막 분석 날짜, 분석한 세션 ID, 패턴별 누적 횟수, 기준 파일 해시 |
| `references/` | 최신 im-not-ai 기준 파일 |

## 출처

- AI 문체 분류 체계와 처방: [epoko77-ai/im-not-ai](https://github.com/epoko77-ai/im-not-ai) (MIT). `references/` 의 `diagnosis-rules.md`·`quick-rules.md`·`ai-tell-taxonomy.md`·`rewriting-playbook.md` 는 그 저장소 파일의 사본이고, 라이선스는 `references/LICENSE-im-not-ai` 에 있습니다.

## 라이선스

MIT — [LICENSE](LICENSE) 참고.
