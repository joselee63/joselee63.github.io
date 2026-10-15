# 한국 · 미국 증시 섹터 차트 (웹 버전)

자동으로 데이터를 모아 차트와 결과표를 만들고, GitHub Pages 웹페이지로 보여줍니다.
- 한국: `https://<아이디>.github.io/<저장소>/` — 평일 21:07 자동 업데이트 (네이버 금융)
- 미국: `https://<아이디>.github.io/<저장소>/us/` — 화~토 07:07 자동 업데이트, 미국장 마감 후 (Yahoo Finance)
- 페이지 오른쪽 위 국기 버튼으로 한국 ↔ 미국을 오갑니다.
서버 없이 GitHub 무료 기능(Actions + Pages)만 사용합니다. 공개 저장소 기준 비용 0원.

- 페이지 상단: **업데이트 완료 시각**, 데이터 기준일, **↻ 업데이트 버튼**(지금 바로 갱신)
- 섹터 강도표 → 종목별 결과표(검색·섹션·추세선·숫자 범위 필터, 정렬) → 섹션별 차트

```
kr-sector-charts/
├─ build_site.py              데이터 수집 · 차트 생성 · 페이지 만들기
├─ stocks.py                  한국 섹터별 종목 리스트 (여기만 고치면 종목 변경)
├─ stocks_us.py               미국 섹터별 종목 리스트 (티커는 Yahoo Finance 기준)
├─ requirements.txt
├─ web/index.html             웹페이지
└─ .github/workflows/daily.yml  자동 실행 일정 (한국 평일 21:07 · 미국 화~토 07:07)
```

---

## 처음 설정 (한 번만, 약 15분)

### 1) 저장소 만들기
GitHub 로그인 → 오른쪽 위 **+** → **New repository**
- Repository name: 예) `kr-sector-charts`
- **Public** 선택 (무료로 Pages를 쓰려면 공개 저장소여야 합니다)
- **Create repository**

### 2) 파일 올리기
**방법 A — 웹에서 (git 몰라도 됨)**
1. 저장소 화면 → **Add file → Upload files**
2. 압축을 푼 폴더 안의 파일·폴더를 전부 끌어다 놓기 → **Commit changes**
3. `.github` 폴더는 숨김 폴더라 맥에서는 안 보여 빠지기 쉽습니다. 저장소에 `.github/workflows/daily.yml`이 없다면:
   **Add file → Create new file** → 파일 이름 칸에 `.github/workflows/daily.yml` 입력 → 내용 붙여넣기 → **Commit changes**

**방법 B — git**
```bash
cd kr-sector-charts
git init -b main && git add -A && git commit -m "init"
git remote add origin https://github.com/<아이디>/kr-sector-charts.git
git push -u origin main
```

### 3) 첫 실행
저장소 → **Actions** 탭 → (처음이면 활성화 버튼 클릭) → 왼쪽 **daily-build** → **Run workflow** → **Run workflow**
3~5분 뒤 초록색 체크가 뜨면 성공입니다. 이때 `gh-pages` 브랜치가 생깁니다.

### 4) 웹페이지 켜기
저장소 → **Settings → Pages**
- Source: **Deploy from a branch**
- Branch: **gh-pages** / **(root)** → **Save**

1~2분 뒤 `https://<아이디>.github.io/kr-sector-charts/` 에서 열립니다. 휴대폰 홈 화면에 추가해 두면 편합니다.

### 5) 업데이트 버튼용 토큰 (기기마다 한 번)
업데이트 버튼은 GitHub에 "지금 실행해줘"라고 요청하는 버튼이라, 본인 확인용 토큰이 필요합니다.

1. GitHub 오른쪽 위 프로필 → **Settings** → 맨 아래 **Developer settings**
2. **Personal access tokens → Fine-grained tokens → Generate new token**
3. 설정
   - Token name: 예) `kr-sector-update`
   - Expiration: 원하는 기간 (만료되면 새로 만들어 다시 입력)
   - Repository access: **Only select repositories** → 이 저장소 선택
   - Permissions → Repository permissions → **Actions: Read and write** (나머지는 그대로)
4. **Generate token** → 나온 토큰 복사
5. 웹페이지에서 **↻ 업데이트** 클릭 → 토큰 붙여넣기

> 토큰은 **그 기기의 브라우저에만** 저장되고, 페이지 코드나 저장소에는 들어가지 않습니다.
> 이 토큰으로 할 수 있는 일은 "이 저장소의 실행 요청"뿐입니다. 공용 PC에서는 입력하지 말고,
> 기기를 잃어버리면 GitHub에서 토큰을 삭제하세요. 페이지의 **토큰 변경**으로 지울 수 있습니다.

토큰이 없는 다른 사람은 페이지를 볼 수만 있고 업데이트를 실행할 수 없습니다.

---

## 평소 운영

| 상황 | 동작 |
|---|---|
| 평일 21:07 | 자동 업데이트. 휴장일(추석 등)은 자동으로 건너뛰고 기존 페이지 유지 |
| 지금 바로 갱신 | 페이지의 **↻ 업데이트** → 진행 상황 표시 → 완료되면 화면이 저절로 새 데이터로 바뀜 (약 4~6분). 휴장일에도 실행됨 |
| 장중에 수동 업데이트 | 그 시점까지의 당일 데이터로 만들어짐 (업데이트 완료 시각으로 구분) |
| 종목 추가·삭제 | GitHub에서 `stocks.py` 열기 → 연필 아이콘 → 수정 → **Commit changes** → 다음 업데이트부터 반영 |
| 종목명 변경·실패 | 페이지 맨 아래 **점검 메모**에 표시됨 |

설정 바꾸기
- 이동평균·차트 길이·추세선: `build_site.py` 맨 위 설정 (`MA_LIST`, `DISPLAY_BARS`, `TREND_LONG` 등)
- 자동 실행 시각: `.github/workflows/daily.yml`의 `cron: "7 21 * * 1-5"` (분 시 * * 요일, 한국시간)

알아둘 점
- **공개 페이지**: 주소를 아는 사람은 누구나 볼 수 있습니다.
- **60일 규칙**: 공개 저장소에서 60일간 활동이 없으면 GitHub가 자동 실행을 끕니다. 매일 배포가 올라가 보통 유지되지만,
  꺼졌다면 Actions 탭 → daily-build → **Enable workflow**.
- 정각 근처에는 GitHub 실행이 몇 분 늦어질 수 있습니다.

---

## 문제 해결

| 증상 | 해결 |
|---|---|
| 배포 단계에서 `403` / `Permission denied` | Settings → Actions → General → Workflow permissions → **Read and write permissions** → Save 후 다시 실행 |
| 실행이 `수신 성공률 … 미만` 으로 실패 | 네이버·야후 모두 응답이 없던 경우. 기존 페이지는 그대로 유지됨. 잠시 후 다시 실행 |
| 업데이트 버튼: "토큰이 올바르지 않거나…" | 토큰의 저장소 선택과 **Actions: Read and write** 권한 확인 후 다시 입력 |
| "실행은 끝났지만 페이지 반영이 늦습니다" | Pages 반영이 늦는 경우. 1~2분 뒤 새로고침 |
| 페이지에 "데이터가 아직 없습니다" | 3)번 첫 실행과 4)번 Pages 설정을 했는지 확인 |

로컬 미리보기 (선택)
```bash
pip install -r requirements.txt
python build_site.py          # 한국 → site/ 폴더 생성
MARKET=us python build_site.py   # 미국 → site/us/ 폴더 생성
# site/index.html 을 브라우저로 열기 (업데이트 버튼은 GitHub에 올린 뒤에만 동작)
```
