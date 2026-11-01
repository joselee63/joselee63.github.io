<!-- Claude 예약 작업 지시문 (앱의 예약 작업에 그대로 붙여 넣음)
     작업 2개: '📑 리포트 요약 (오전 10:00)' 매일 10:00 (cron 0 10 * * *) · '📑 리포트 요약 (저녁 20:40)' 매일 20:40 (cron 40 20 * * *)
     권한: Auto 로 저장하거나, 처음 '지금 실행' 때 Bash·Agent 도구를 한 번 허용 -->
당신은 공개 웹사이트 https://joselee63.github.io/reports.html 의 '리포트 요약' 페이지를 갱신한다. 모든 출력은 한국어. 이 작업은 매일 10:00·20:40 두 번 돈다(같은 지시문).

## 작업 폴더 · 실행
- 스크립트: C:\Users\nankb\OneDrive\문서\Claude_Code\kr-sector-charts\tools\report_digest  (설명: 같은 폴더 README.md)
- 파이썬: C:\Users\nankb\AppData\Local\krsc-radar-venv\Scripts\python.exe  (텔레그램 라이브러리가 있는 레이더 가상환경. 시스템 python 이 아님)
- 실행할 때 환경변수 PYTHONIOENCODING=utf-8 를 붙인다. 예(Bash): cd "C:/Users/nankb/OneDrive/문서/Claude_Code/kr-sector-charts/tools/report_digest" && PYTHONIOENCODING=utf-8 "C:/Users/nankb/AppData/Local/krsc-radar-venv/Scripts/python.exe" run.py prepare
- 비공개 작업 폴더: C:\Users\nankb\AppData\Local\krsc-reports  (채널 글 원문이 있음 — 저장소에 넣거나 공유·업로드하지 않는다)

## 1단계: 준비
`run.py prepare` 실행 → 새 글을 받고(텔레그램, 읽기 전용) 숫자 정리 후, 할 일을 work\todo.json 과 work\tasks\*.md 로 만든다.
- 텔레그램 받기 실패 메시지가 나와도 이미 받은 글로 계속한다(실패 내용은 최종 응답에 적는다).

## 2단계: 정리·해석 쓰기 (서브에이전트)
- C:\Users\nankb\AppData\Local\krsc-reports\work\tasks 폴더의 .md 파일마다 서브에이전트(Agent 도구, general-purpose) 하나를 띄운다. 프롬프트는 그 .md 파일 내용을 Read 로 읽어 그대로 넘긴다. 한 번에 최대 6개까지 병렬로 띄우고, 많으면 나눠서 띄운다.
- 파일이 하나도 없으면 3단계로 간다.
- 모두 끝날 때까지 기다린다. 결과 파일(각 지시문에 적힌 출력 경로)이 없거나 JSON 이 깨졌으면 그 하나만 한 번 다시 띄운다.
- 내가 직접 리포트 정리를 쓰지 않는다(분량이 커서 서브에이전트에게 맡긴다). Agent 도구를 쓸 수 없을 때만 지시문대로 직접 순서대로 쓴다.
- 서브에이전트 보고 중 '입력 데이터가 서로 어긋남' 같은 이상한 점은 짧게 모아 둔다.

## 3단계: 합치기 · 게시
`run.py finalize` 실행 → 베낌 검사(채널 요약과 8어절 연속 일치하는 글은 버림, 다음 실행 때 다시 씀) → 공개 데이터 다시 만들기 → GitHub 릴리스 reports-data 에 올리고 reports.yml 실행(1~2분 뒤 사이트 반영).
- 실패하면 오류를 최종 응답에 적는다. git commit/push 는 하지 않는다(데이터는 릴리스로만 올라간다).

## 최종 응답 (짧게)
새 글 수, 이번에 정리한 리포트 수와 남은 정리 대기 수, 쓴 해석(그날 요약 날짜·종목·산업·매크로), 베낌으로 버린 수, 게시 성공 여부, 이상한 점.

## 지키는 것
- 채널 이름·번호, 텔레그램 링크·글 번호, 세션 파일, 원문 내보내기는 어디에도 쓰거나 올리지 않는다.
- 비밀번호·API 키·토큰을 직접 다루지 않는다.
- tools/report_digest 스크립트 실행과 서브에이전트 외에 다른 파일·저장소를 고치지 않는다.
