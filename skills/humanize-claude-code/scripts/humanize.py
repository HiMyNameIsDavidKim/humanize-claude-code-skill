"""humanize-claude-code 스킬의 결정적 처리를 모은 스크립트.

모델이 판단해야 하는 일(세션별 AI 문체 판정, 항목 문구 작성)만 SKILL.md 가 맡고,
세션 고르기·텍스트 추출·횟수 누적·가이드 재구성·훅 출력은 여기서 한다.
훅에서도 불리므로 표준 라이브러리만 쓰고 macOS·Windows 의 python 3.8 이상에서 돈다.

상태·가이드·기준 사본은 플러그인 데이터 폴더(${CLAUDE_PLUGIN_DATA})에 둔다.
플러그인 폴더는 업데이트할 때마다 바뀌어서 그 안에 쓰면 상태가 사라진다.

사용법:
    python3 humanize.py <서브커맨드> <데이터 폴더>

서브커맨드:
    hook     SessionStart 훅. 가이드를 주입하고 분석이 필요하면 알림을 띄운다
    refs     im-not-ai 원본 기준 파일이 바뀌었는지 보고 바뀌었으면 갱신한다
    collect  프로젝트별 미분석 세션을 최대 10개씩 골라 응답 텍스트를 work/ 에 뽑는다
    commit   work/run.json 판정 결과를 누적하고 guide.md·evicted.md 를 다시 쓴다
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
import shutil
import sys
import urllib.request
import webbrowser
from pathlib import Path
from typing import Dict, List, TypedDict

DEFAULT_SKILL_NAME = "humanize-claude-code"
DEFAULT_SKILL_COMMAND = "/humanize-claude-code:humanize-claude-code"
DEFAULT_SESSIONS_PER_PROJECT = 10
DEFAULT_GUIDE_LIMIT = 15
DEFAULT_RECUR_SESSIONS = 2
DEFAULT_ALERT_DAYS = 7
DEFAULT_REFERENCE_BASE = (
    "https://raw.githubusercontent.com/epoko77-ai/im-not-ai/main/skills/humanize-korean/references/"
)
DEFAULT_REFERENCE_FILES = ("diagnosis-rules.md", "quick-rules.md")
DEFAULT_SKILL_REPO = "https://github.com/HiMyNameIsDavidKim/humanize-claude-code-skill"

BUNDLED_REFERENCES = Path(__file__).resolve().parent.parent / "references"
PROJECTS_DIR = Path.home() / ".claude" / "projects"
DATA_DIR = Path(sys.argv[2])
STATE_PATH = DATA_DIR / "state.json"
GUIDE_PATH = DATA_DIR / "guide.md"
EVICTED_PATH = DATA_DIR / "evicted.md"
ALERT_PATH = DATA_DIR / "alert.html"
REFERENCES_DIR = DATA_DIR / "references"
WORK_DIR = DATA_DIR / "work"
MANIFEST_PATH = WORK_DIR / "manifest.json"
RUN_PATH = WORK_DIR / "run.json"

CODE_FENCE = re.compile(r"```.*?```", re.S)


class ItemText(TypedDict):
    """가이드 항목 한 줄을 이루는 문구."""

    rule: str
    instead: str


class EvictedEntry(TypedDict):
    """가이드에서 뺀 항목의 기록."""

    evicted_on: str
    count_at_eviction: int
    recurrences: List[List[str]]


class State(TypedDict):
    """state.json 의 형태."""

    last_analyzed: str
    analyzed_ids: List[str]
    counts: Dict[str, int]
    items: Dict[str, ItemText]
    guide: List[str]
    evicted: Dict[str, EvictedEntry]
    reference_sha: Dict[str, str]


class ManifestSession(TypedDict):
    """collect 가 고른 세션 하나."""

    id: str
    project: str
    chars: int


class Manifest(TypedDict):
    """collect 결과. commit 이 이것과 run.json 을 맞춰 본다."""

    current: str
    sessions: List[ManifestSession]


class RunResult(TypedDict):
    """모델이 work/run.json 에 쓰는 판정 결과."""

    sessions: Dict[str, List[str]]
    items: Dict[str, ItemText]


class HumanizeError(RuntimeError):
    """판정 결과가 collect 결과와 맞지 않아 반영할 수 없을 때 발생한다."""


def load_state() -> State:
    """state.json 을 읽는다. 아직 없으면 빈 상태를 돌려준다.

    Returns:
        현재 상태.
    """
    if not STATE_PATH.exists():
        return State(
            last_analyzed="",
            analyzed_ids=[],
            counts={},
            items={},
            guide=[],
            evicted={},
            reference_sha={},
        )
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: State) -> None:
    """state.json 에 쓴다.

    Args:
        state: 저장할 상태.
    """
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def list_sessions() -> List[Path]:
    """모든 프로젝트의 세션 기록 파일을 돌려준다.

    서브에이전트 기록은 세션 폴더 안에 따로 있으므로 프로젝트 폴더 바로 아래 jsonl 만 본다.

    Returns:
        세션 기록 파일 경로 목록.
    """
    return list(PROJECTS_DIR.glob("*/*.jsonl"))


def session_text(path: Path) -> str:
    """세션 기록에서 Claude 응답 텍스트만 뽑는다.

    도구 호출·도구 결과·thinking·서브에이전트 줄은 건너뛰고, 코드 블록은 지운다.

    Args:
        path: 세션 기록 파일.

    Returns:
        응답 사이를 구분선으로 이은 텍스트.
    """
    texts: List[str] = []
    with path.open(encoding="utf-8") as lines:
        for line in lines:
            record = json.loads(line)
            if record.get("type") != "assistant" or record.get("isSidechain"):
                continue
            content = record.get("message", {}).get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if block.get("type") == "text":
                    text = CODE_FENCE.sub("", block["text"]).strip()
                    if text:
                        texts.append(text)
    return "\n\n---\n\n".join(texts)


def find_current_session() -> str:
    """지금 스킬을 돌리는 세션 ID 를 찾는다.

    스킬이 도는 동안 계속 기록되는 파일이라 가장 최근에 수정됐고, 안에 스킬 호출이 있다.

    Returns:
        현재 세션 ID. 찾지 못하면 빈 문자열.
    """
    for path in sorted(list_sessions(), key=lambda p: p.stat().st_mtime, reverse=True):
        if DEFAULT_SKILL_NAME in path.read_text(encoding="utf-8"):
            return path.stem
    return ""


def count_pending(state: State, exclude_id: str) -> int:
    """아직 분석하지 않은 세션 수를 센다.

    Args:
        state: 현재 상태.
        exclude_id: 셈에서 뺄 세션 ID(진행 중인 세션).

    Returns:
        미분석 세션 수.
    """
    analyzed = set(state["analyzed_ids"])
    return sum(1 for p in list_sessions() if p.stem not in analyzed and p.stem != exclude_id)


def open_alert(message: str) -> None:
    """할 일을 적은 로컬 HTML 을 기본 브라우저로 연다.

    VS Code 확장이 SessionStart 의 systemMessage 를 화면에 그리지 않아 OS 와 상관없이 보이는 경로로 알린다.

    Args:
        message: 분석 경과와 미분석 세션 수를 담은 문장.
    """
    ALERT_PATH.write_text(
        '<!doctype html><meta charset="utf-8"><title>humanize-claude-code</title>'
        "<style>html{background:#16181c;color:#d4d7dd}a{color:#8ab4f8}code{background:#2a2d33;padding:2px 6px;"
        "border-radius:4px}</style>"
        '<body style="font-family:sans-serif;max-width:640px;margin:48px auto;padding:0 16px;line-height:1.6">'
        f"<h1>응답 문체 분석이 필요합니다</h1><p>{message}</p>"
        f"<p>Claude Code 에서 <code>{DEFAULT_SKILL_COMMAND}</code> 를 실행하세요.</p>"
        f'<p>스킬 저장소: <a href="{DEFAULT_SKILL_REPO}">HiMyNameIsDavidKim/humanize-claude-code-skill</a></p></body>',
        encoding="utf-8",
    )
    webbrowser.open(ALERT_PATH.as_uri())


def run_hook() -> None:
    """SessionStart 훅. 가이드를 주입하고, 분석 주기가 지났으면 유저에게 알린다.

    브라우저 알림은 새 세션 시작에서만 띄운다. 압축·/clear·재개에서도 이 훅이 돌기 때문이다.
    출력 JSON 은 ASCII 로 이스케이프한다. Windows 에서 콘솔 인코딩이 끼어들어도 깨지지 않게 하기 위해서다.
    """
    hook_input: Dict[str, str] = json.loads(sys.stdin.read() or "{}")
    session_id = hook_input.get("session_id", "")
    state = load_state()
    output: Dict[str, object] = {}
    if GUIDE_PATH.exists():
        output["hookSpecificOutput"] = {
            "hookEventName": "SessionStart",
            "additionalContext": GUIDE_PATH.read_text(encoding="utf-8"),
        }
    pending = count_pending(state, session_id)
    if state["last_analyzed"]:
        days = (datetime.date.today() - datetime.date.fromisoformat(state["last_analyzed"])).days
        due = days >= DEFAULT_ALERT_DAYS
        since = f"마지막 분석 후 {days}일 지남"
    else:
        due = True
        since = "아직 분석한 적 없음"
    if due and pending:
        message = f"{since}, 미분석 세션 {pending}개."
        output["systemMessage"] = f"[{DEFAULT_SKILL_NAME}] {message} {DEFAULT_SKILL_COMMAND} 를 실행하세요."
        if hook_input.get("source") == "startup":
            open_alert(message)
    if output:
        print(json.dumps(output))


def run_refs() -> None:
    """im-not-ai 원본 기준 파일을 받아 데이터 폴더 사본과 비교하고, 다르면 갱신한다.

    사본이 아직 없으면 플러그인에 묶어 배포한 파일로 먼저 채운다.
    받기에 실패하면 기존 사본을 그대로 쓰도록 실패만 알리고 넘어간다.
    """
    state = load_state()
    REFERENCES_DIR.mkdir(exist_ok=True)
    for name in DEFAULT_REFERENCE_FILES:
        local = REFERENCES_DIR / name
        if not local.exists():
            shutil.copyfile(BUNDLED_REFERENCES / name, local)
        try:
            with urllib.request.urlopen(DEFAULT_REFERENCE_BASE + name, timeout=20) as response:
                remote = response.read()
        except OSError as error:
            print(f"{name}: 받기 실패, 기존 사본 사용 ({error})")
            continue
        sha = hashlib.sha256(remote).hexdigest()
        if hashlib.sha256(local.read_bytes()).hexdigest() == sha:
            print(f"{name}: 변경 없음")
        else:
            local.write_bytes(remote)
            print(f"{name}: 원본이 바뀌어 갱신함")
        state["reference_sha"][name] = sha
    save_state(state)


def run_collect() -> None:
    """프로젝트별 미분석 세션을 최대 10개씩 골라 응답 텍스트를 work/ 에 쓴다."""
    state = load_state()
    analyzed = set(state["analyzed_ids"])
    current = find_current_session()
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    WORK_DIR.mkdir()
    sessions: List[ManifestSession] = []
    for project in sorted(p for p in PROJECTS_DIR.iterdir() if p.is_dir()):
        candidates = [p for p in project.glob("*.jsonl") if p.stem not in analyzed and p.stem != current]
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for path in candidates[:DEFAULT_SESSIONS_PER_PROJECT]:
            text = session_text(path)
            if text:
                (WORK_DIR / f"{path.stem}.txt").write_text(text, encoding="utf-8")
            sessions.append(ManifestSession(id=path.stem, project=project.name, chars=len(text)))
    manifest = Manifest(current=current, sessions=sessions)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    to_read = [s for s in sessions if s["chars"]]
    print(f"현재 세션: {current or '찾지 못함'}")
    print(f"고른 세션 {len(sessions)}개, 읽을 세션 {len(to_read)}개(응답 텍스트가 없는 세션은 기록만 한다)")
    for s in to_read:
        print(f"{WORK_DIR / (s['id'] + '.txt')}\t{s['chars']}자\t{s['project']}")


def render_guide(state: State, today: str) -> str:
    """가이드 문서를 만든다.

    Args:
        state: 반영을 마친 상태.
        today: 갱신 날짜.

    Returns:
        guide.md 내용.
    """
    lines = [
        f"# 응답 문체 가이드 ({DEFAULT_SKILL_NAME}, 갱신 {today})",
        "",
        "지난 세션 응답에서 반복해 나온 AI 문체다. 응답을 쓸 때 아래 표현을 쓰지 말고 '대신' 형태로 쓴다.",
        "",
    ]
    for pattern_id in state["guide"]:
        item = state["items"][pattern_id]
        lines.append(f"- **{pattern_id}** {item['rule']} → 대신: {item['instead']}")
    return "\n".join(lines) + "\n"


def render_evicted(state: State) -> str:
    """가이드에서 뺀 항목 문서를 만든다.

    Args:
        state: 반영을 마친 상태.

    Returns:
        evicted.md 내용.
    """
    lines = [
        "# 가이드에서 뺀 항목",
        "",
        f"재발 기록은 분석 회차마다 그 패턴이 지배 패턴으로 나온 세션 수다. "
        f"한 회차에 {DEFAULT_RECUR_SESSIONS}세션 이상 재발하면 그 회차에 가이드로 되돌린다.",
        "",
        "| ID | 내용 | 뺀 날짜 | 뺄 때 누적 | 재발 기록 |",
        "|---|---|---|---|---|",
    ]
    for pattern_id, entry in sorted(state["evicted"].items()):
        recur = ", ".join(f"{d} {n}세션" for d, n in entry["recurrences"]) or "-"
        rule = state["items"][pattern_id]["rule"]
        lines.append(f"| {pattern_id} | {rule} | {entry['evicted_on']} | {entry['count_at_eviction']} | {recur} |")
    return "\n".join(lines) + "\n"


def run_commit() -> None:
    """work/run.json 판정 결과를 누적하고 가이드를 다시 만든다.

    Raises:
        HumanizeError: 판정하지 않은 세션이 있거나, 문구가 없는 패턴이 있을 때.
    """
    state = load_state()
    manifest: Manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    run: RunResult = json.loads(RUN_PATH.read_text(encoding="utf-8"))
    expected = {s["id"] for s in manifest["sessions"] if s["chars"]}
    missing = expected - set(run["sessions"])
    if missing:
        raise HumanizeError(f"판정하지 않은 세션: {sorted(missing)}")

    this_run: Dict[str, int] = {}
    for patterns in run["sessions"].values():
        for pattern_id in set(patterns):
            this_run[pattern_id] = this_run.get(pattern_id, 0) + 1
    for pattern_id, n in this_run.items():
        state["counts"][pattern_id] = state["counts"].get(pattern_id, 0) + n
        if pattern_id not in state["items"]:
            if pattern_id not in run["items"]:
                raise HumanizeError(f"문구가 없는 새 패턴: {pattern_id}")
            state["items"][pattern_id] = run["items"][pattern_id]

    today = datetime.date.today().isoformat()
    for pattern_id, entry in state["evicted"].items():
        if this_run.get(pattern_id):
            entry["recurrences"].append([today, str(this_run[pattern_id])])
    reinserted = [i for i in state["evicted"] if this_run.get(i, 0) >= DEFAULT_RECUR_SESSIONS]
    # 최소 구현: 누적 순위로만 고르므로, 가이드 덕에 줄어든 항목이 빠졌다가 재발하면 되돌아오는 순환이 생긴다
    ranked = sorted(state["counts"], key=lambda i: (-state["counts"][i], i))
    previous = state["guide"]
    state["guide"] = (reinserted + [i for i in ranked if i not in reinserted])[:DEFAULT_GUIDE_LIMIT]
    newly_evicted = [i for i in previous if i not in state["guide"]]
    for pattern_id in newly_evicted:
        state["evicted"][pattern_id] = EvictedEntry(
            evicted_on=today, count_at_eviction=state["counts"][pattern_id], recurrences=[]
        )
    for pattern_id in state["guide"]:
        state["evicted"].pop(pattern_id, None)

    state["last_analyzed"] = today
    new_ids = [s["id"] for s in manifest["sessions"]] + ([manifest["current"]] if manifest["current"] else [])
    state["analyzed_ids"] = sorted(set(state["analyzed_ids"]) | set(new_ids))
    save_state(state)
    GUIDE_PATH.write_text(render_guide(state, today), encoding="utf-8")
    EVICTED_PATH.write_text(render_evicted(state), encoding="utf-8")
    shutil.rmtree(WORK_DIR)

    print(f"분석 세션 {len(manifest['sessions'])}개 반영, 이번 회차 패턴: {this_run}")
    print(f"가이드 {len(state['guide'])}개: {[(i, state['counts'][i]) for i in state['guide']]}")
    print(f"새로 뺀 항목: {newly_evicted or '-'}")
    print(f"되돌린 항목: {reinserted or '-'}")


if __name__ == "__main__":
    # Windows 는 파이프 입출력에 시스템 인코딩(cp949 등)을 써서, 훅 입력의 한글 경로와 모델이 읽는 출력이 깨진다
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    {"hook": run_hook, "refs": run_refs, "collect": run_collect, "commit": run_commit}[sys.argv[1]]()
