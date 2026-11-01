"""공개 데이터(out/data.json · out/ai.json) → GitHub 릴리스 reports-data 에 덮어쓰기 → reports.yml 로 사이트에 반영
(저장소 기록에 쌓이지 않게 릴리스 첨부 파일을 씀 — 종가베팅 closebet-data 와 같은 방식. 이 PC의 gh 로그인을 씀)
"""
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import common as C  # noqa: E402

GH = shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"


def gh(*args, check=True):
    r = subprocess.run([GH, *args, "-R", C.REPO_SLUG], capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        raise SystemExit(f"gh {' '.join(args[:3])} 실패: {(r.stderr or r.stdout).strip()[:300]}")
    return r


def publish():
    files = [str(C.OUT / "data.json"), str(C.OUT / "ai.json")]
    for f in files:
        if not Path(f).exists():
            raise SystemExit(f"{f} 없음 — 먼저 run.py build")
    if gh("release", "view", C.RELEASE, check=False).returncode != 0:
        gh("release", "create", C.RELEASE, "--prerelease", "--title", "리포트 요약 데이터",
           "--notes", "리포트 요약 페이지(reports.html) 데이터 — 하루 두 번 덮어씀. 증권사 리포트의 사실 정보와 이 사이트가 쓴 정리·해석.")
    gh("release", "upload", C.RELEASE, *files, "--clobber")
    gh("workflow", "run", "reports.yml", "--ref", "main")
    C.save_state(published_at=C.kst_now().isoformat(timespec="seconds"))
    print(f"[publish] 릴리스 {C.RELEASE} 에 올림 → reports.yml 시작 (1~2분 뒤 {C.SITE}/reports.html)")


if __name__ == "__main__":
    publish()
