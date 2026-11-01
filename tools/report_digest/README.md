# 리포트 요약 (reports.html)

증권사 리포트를 하루 두 번 모아 **사실 정보 + 우리 말 정리 + Claude 해석**으로 공개하는 페이지입니다.
https://joselee63.github.io/reports.html

## 흐름

```
텔레그램(구독 채널) ──읽기 전용──▶ 내 PC  %LOCALAPPDATA%\krsc-reports\msgs.jsonl   (원문, 비공개)
                                    │ parse.py · build.py   숫자 정리(목표가 변화·종목/산업 모아 보기·언급·검색)
                                    │ work.py prepare       Claude 할 일 → work\tasks\*.md
                                    │ (Claude 예약 작업이 서브에이전트로 정리·해석 작성)
                                    │ work.py merge         베낌 검사 → rw.jsonl · ai\
                                    ▼
                         out\data.json · out\ai.json  ──publish.py──▶ GitHub 릴리스 reports-data
                                                                      └▶ reports.yml → gh-pages/reports/
                                                                      └▶ daily.yml(전체 빌드)도 같은 파일을 넣음
```

| 시각 | 하는 일 |
|---|---|
| 10:00 · 20:40 매일 | Claude 예약 작업 `리포트 요약 (오전/저녁)` — `run.py prepare` → 서브에이전트 → `run.py finalize` |
| 버튼 '지금 업데이트' | 이 PC 도우미(`reports.bat`, 127.0.0.1:8792)가 `run.py update` — 새 글 받기·숫자 정리·게시 (해석은 다음 예약 때) |

리포트는 하루 네 번 묶음으로 올라옵니다(08:15~08:50, 12:45~13:25, 16:10~16:40, 20:10~20:30). 그래서 저녁은 20:40.

## 명령 (레이더 가상환경 파이썬)

```
set PY=%LOCALAPPDATA%\krsc-radar-venv\Scripts\python.exe
%PY% run.py update      새 글 → 숫자 정리 → 게시
%PY% run.py prepare     새 글 → 숫자 정리 → Claude 할 일 만들기
%PY% run.py finalize    Claude 결과 합치기 → 게시   (--no-push: 게시 안 함)
%PY% run.py status      저장소 상태
```

## 공개 범위

- 공개: 제목·증권사·애널리스트·투자의견·목표가·발간일(사실 정보), 리포트마다 우리 말 정리(핵심 논지·근거 수치·실적 추정·목표가/의견·리스크·해석), 날짜·종목·산업·매크로 해석, 원문 찾기 링크(네이버 금융 리서치 — 주소만 만들고 수집하지 않음).
- 하지 않음: 원문 PDF 재게시, 리포트 본문·채널 요약 문장 복사(8어절 연속 일치하면 자동으로 버림).
- 비공개(이 PC에만): 채널 이름·번호(`config.json`), 텔레그램 글 번호(공개 번호는 비밀 소금으로 해시), 채널 글 원문, 텔레그램 세션.
  세션은 레이더 것(`%LOCALAPPDATA%\krsc-radar\telegram.session`)을 **읽기 전용**으로 열어 메모리에서만 씀 — 파일에 쓰지 않으므로 레이더와 부딪히지 않음.

## 목표가 변화 판정

① 본문 '기존 X원에서' ② 목표주가 줄의 '(유지)' ③ 본문 '목표주가 N% 상향/하향' ④ 같은 증권사 직전 기록(0.55~2.2배·200일 안, 본문 방향과 어긋나지 않을 때) ⑤ 상향/하향 단어만 ⑥ '확인 필요'(액면분할 등) / '첫 기록'.

## 처음 설치 (한 번만, 2026-11-02 완료)

```
%PY% run.py bootstrap <텔레그램 JSON 내보내기 result.json>    채널 번호·소금·지난 글
%PY% run.py import <rw_out 폴더> [<ai 폴더>]                  시안 때 만든 정리·해석
```

## 사용량

리포트 1건 정리에 Claude 토큰 약 2,500~3,000개. 한 번 실행에 최대 240건(4묶음) + 그날 요약·종목·산업·매크로.
줄이려면 `work.py` 의 `RW_CAP`(한 번에 정리할 수)을 낮추세요. 정리 못 한 리포트는 사실 정보만 보이고, 다음 실행 때 최신부터 채웁니다.
