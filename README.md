# Podcast Study

팟캐스트 새 에피소드가 올라오면 자동으로 **요약 · 핵심 표현 · 스크롤 싱크 스크립트 플레이어 · 회화 질문**을 만들어 주는 개인 영어학습 사이트.

```
GitHub Actions (3시간마다)
  └─ pipeline/  RSS 확인 → 새 에피소드 → 자막(VTT/SRT) 다운로드 → 문단화
       └─ Claude API → 요약/표현/질문/화자 매핑/한국어 번역 (JSON)
            └─ docs/data/*.json 커밋 → GitHub Pages가 docs/ 를 그대로 서빙
```

- 음원은 저장하지 않고 발행사 CDN에서 스트리밍합니다. 자막은 발행사가 RSS `<podcast:transcript>` 태그로 공개 배포하는 파일을 그대로 사용합니다.
- 기본 대상: **Big Take**, **Big Take Asia** (Bloomberg, Omny), **Think Fast, Talk Smart** (Stanford GSB, Transistor). 세 쇼 모두 타임스탬프가 있는 자막을 RSS로 제공해서 문장 단위 싱크가 됩니다.

## 처음 설정 (10분)

1. **리포지토리 만들기** — GitHub에 새 리포(예: `podcast-study`)를 만들고 이 폴더를 통째로 푸시합니다.
   ```bash
   git init && git add -A && git commit -m "init"
   git branch -M main
   git remote add origin https://github.com/<you>/podcast-study.git
   git push -u origin main
   ```
   무료 계정에서 GitHub Pages를 쓰려면 리포가 **Public**이어야 합니다. 자막 텍스트가 공개 저장된다는 뜻이니, 원치 않으면 Private 리포 + Cloudflare Pages(무료) 조합으로 바꿀 수 있습니다(아래 참고).
2. **API 키** — 리포 `Settings → Secrets and variables → Actions → New repository secret`
   이름 `ANTHROPIC_API_KEY`, 값은 본인 키. (선택) `Variables`에 `STUDY_MODEL`을 두면 모델을 바꿀 수 있습니다. 기본값 `claude-sonnet-5-5`.
3. **Pages 켜기** — `Settings → Pages → Build and deployment → Source: Deploy from a branch`, Branch `main`, Folder `/docs`, Save.
4. **첫 실행** — `Actions → Update podcast study → Run workflow`. `backfill`을 3으로 두면 쇼마다 최신 3편을 만듭니다(약 3~6분). 끝나면 `https://<you>.github.io/podcast-study/` 에서 확인.
5. 이후에는 3시간마다 자동으로 돌며 새 에피소드만 추가합니다. 수동 실행도 언제든 가능합니다.

기본 포함된 `Why Airlines Sell More Seats…`는 **데모 에피소드**(가짜 콘텐츠 + 신호음 음원)입니다. 실제 에피소드가 쌓이면 `docs/data/episodes/big-take-2026-10-09-why-airlines-*.json`과 `docs/demo/`를 지우고 커밋하세요.

## 로컬에서 돌리기

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
python -m pipeline --backfill 1          # 실제 실행
python -m pipeline --mock                 # API 없이 배관만 확인
python -m pipeline --force "Jane Street"  # 특정 에피소드 다시 생성
python -m pytest -q                       # 파서 테스트
python -m RangeHTTPServer 8000 --directory docs   # 로컬 미리보기 (pip install RangeHTTPServer)
```

## 쇼 추가하기

`config/shows.yaml`에 항목을 추가합니다. 두 종류를 지원합니다.

- **RSS 자막 쇼**: 아이템에 `<podcast:transcript>` 태그(VTT/SRT/JSON)가 있는 쇼. 완전 자동.
- **웹 대본 쇼** (`transcript: web`): 대본이 에피소드 페이지에만 있는 쇼(BBC Learning English, NPR, HBR 등). 파이프라인이 음원을 받아 Whisper로 인식한 뒤 대본 문장을 정렬해 타임스탬프를 만듭니다. 사이트별 파서(`pipeline/webtranscript.py`)가 필요합니다 — 현재 `bbc_le`, `voa_le`, `generic`.

```yaml
  - slug: money-stuff
    name: "Money Stuff: The Podcast"
    publisher: Bloomberg
    color: "#7c3aed"
    feed: https://omny.fm/shows/money-stuff-the-podcast/playlists/podcast.rss
    speaker_labels: generic    # Omny는 'Speaker 1' 식 라벨 → 이름은 Claude가 추론
    max_minutes: 60            # 쇼별로 길이 제한을 늘릴 수 있음
```

- `speaker_labels`: `generic`(Speaker 1…), `none`(라벨 없음 → 문단별로 화자 추정), `named`(실명), `auto`.
- 자막 태그가 없는 쇼(NPR, HBR 등 웹페이지에만 스크립트가 있는 경우)는 `pipeline/transcript.py`에 사이트별 파서를 추가해야 하고, 타임스탬프가 없어 싱크는 추정이 됩니다.

## 광고와 싱크 맞추기 (자동)

Big Take(Omny/iHeart)와 Think Fast Talk Smart(Transistor) 모두 **재생할 때마다 광고를 동적으로 끼워 넣습니다**(DAI). 자막 타임스탬프는 광고 없는 원본 기준이라 그대로 두면 광고 길이만큼 밀립니다. 이 프로젝트는 음원을 저장하지 않고 다음처럼 자동으로 맞춥니다.

1. **서버(Actions)**: 에피소드당 한 번 음원을 내려받아 Whisper(base.en)로 "자막의 본편이 광고 뒤 어디서 시작·재개되는지"를 찾고, 그 지점부터 45초 분량의 **오디오 지문**(수 KB)만 `docs/data/sync/`에 저장합니다. 음원은 버립니다. Omny 쇼는 클립 API의 광고 삽입 위치를 힌트로 씁니다.
2. **브라우저**: 발행사 스트림을 한 번 내려받아(팟캐스트 앱과 같은 방식이라 발행사 집계·광고 그대로) 메모리에서 재생하고, 광고 뒤 구간의 지문을 서버 지문과 맞춰 오프셋을 자동으로 잡습니다. 보통 1초 안에 끝나고 "자동 싱크 완료 · 광고 N구간" 토스트가 뜹니다.
3. 실패하면 수동 모드로 떨어집니다: "광고가 끝나고 첫 문장이 들리면 눌러 주세요" 안내 → **지금 들려요**, 또는 플레이어의 **싱크** 버튼(`S`) 후 들리는 문장 탭. 더블클릭(`F`)은 ±0.3/±1초 미세 조정.

지문 알고리즘은 `pipeline/fingerprint.py`와 `docs/assets/sync.js`에 같은 내용이 구현돼 있습니다(8 kHz, 256 ms 창, 64 ms 홉, 300–3000 Hz 16밴드, 부호 비트 15개). 실제 에피소드에서 다른 다운로드(다른 광고 세트)끼리 비트 오류율 0.02–0.2, 무작위 위치는 0.48로 안정적으로 구분됩니다.

## 동작 세부

- API 키가 잘못되거나(401) 크레딧이 부족하면 첫 에피소드에서 실행을 멈추고 재시도 횟수를 소모하지 않습니다. 시크릿을 고친 뒤 다시 실행하면 됩니다.
- `state/seen.json`이 처리 이력입니다. `done`, `skipped_long`(40분 초과), `pending_transcript`(자막 태그가 아직 없음 → 4일간 재시도), `no_transcript`, `failed`(다음 실행 때 재시도).
- 한 번에 최대 6편(`--max-new`)만 처리합니다. 밀린 건 다음 실행으로 넘어갑니다.
- 에피소드당 Claude API 호출 2회(학습팩 + 번역). Sonnet 기준 에피소드당 대략 US$0.15 안팎, 한 달 25편이면 US$4 내외.
- 페이지 단축키: `Space` 재생/정지, `← →` 5초, `[ ]` 속도, `L` 문단 반복, `T` 한국어, `H` 형광펜, `A` 자동 스크롤.
- 재생 위치·완료 여부·설정은 브라우저(localStorage)에만 저장됩니다.

## Private으로 쓰고 싶다면

Private 리포에서는 무료 GitHub Pages가 안 됩니다. 대신 Cloudflare Pages(무료)에 리포를 연결하고 빌드 출력 디렉터리를 `docs`로 두면 같은 사이트가 뜹니다. Cloudflare Access(무료, 50명까지)로 이메일 로그인까지 걸 수 있습니다. 파이프라인 쪽은 바꿀 게 없습니다.

## 폴더

```
config/shows.yaml      쇼 목록·설정
pipeline/              feeds.py(RSS) transcript.py(VTT/SRT 파싱·문단화) llm.py(Claude) build.py main.py
docs/                  정적 사이트 (index.html, episode.html, assets/, data/, demo/)
state/seen.json        처리 이력
tests/                 파서 테스트 + 픽스처(데모 에피소드 소스)
.github/workflows/     3시간 주기 자동 실행
```
