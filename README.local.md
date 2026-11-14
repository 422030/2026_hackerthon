# 전공 교재 접근성 변환기

시각장애 대학생이 전공 교재 PDF 를 올리면, OCR 이 버리는 도표·수식·각주를
AI 가 서술로 복원해 스크린리더로 읽을 수 있는 문서로 바꾼다.

## 지금 상태

**전 구간이 실제 AI 로 끝까지 돈다.** Gemini 가 붙어 있고, 샘플 PDF 와
실제 PDF 양쪽에서 변환이 완료된다. 페이지당 약 12초.

화면은 세 개다. 업로드, 결과(읽기 · 일반 OCR 과 비교), 보관함.

## 설치

### 1. 파이썬 패키지

```
uv venv --python 3.11
uv pip install -r requirements.txt
```

### 2. Tesseract (OCR 엔진)

UB-Mannheim 배포판을 설치하고 `kor` traineddata 를 같이 받는다.
없어도 서버는 뜬다. 다만 PDF 안에 글자 정보가 들어 있는 경우만 처리되고,
스캔본(사진으로 된 PDF)은 빈 결과가 나온다.

### 3. API 키

Google AI Studio 에서 Gemini 키를 발급받아 환경변수로 둔다. 무료다.

PowerShell 에서:

```
setx GEMINI_API_KEY "발급받은_키"
```

설정한 뒤 **터미널을 새로 연다.** `setx` 는 이미 떠 있는 창에는 반영되지 않는다.

키를 코드나 파일에 적지 않는다. 깃에 올라간다.

## 실행

```
.venv\Scripts\python smoke_test.py                                   # 가짜 데이터 검사
.venv\Scripts\python make_sample.py                                  # 샘플 PDF 생성
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8010    # 서버
```

브라우저에서 http://localhost:8010 을 연다.

`localhost` 는 "이 컴퓨터"라는 뜻이다. 다른 사람은 이 주소로 들어올 수 없다.
같은 와이파이에 있는 사람에게 보여주려면:

```
.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8010
```

`ipconfig` 로 확인한 IPv4 주소와 포트(`192.168.x.x:8010`)로 접속한다.
이때 변환은 전부 서버를 띄운 사람의 API 키로 돌아간다.

## 구조

```
PDF 업로드
    ↓
코드가 페이지마다 반복  ← jobs.py 의 for 문이 본체
   ingest.load_pages     PDF → 페이지 PNG + 네이티브 텍스트층
   ocr.run_ocr           글자 + 좌표 (구조 없음)
   adapter.analyze_page  이미지 + OCR → 구조화 JSON   ← AI 는 여기만
   guard.cross_check     둘을 대조해 의심 표시
    ↓
assemble.assemble  (AI 아님)
   머리글 제거 / 페이지 걸친 문단 병합 / heading 레벨 정규화 / 각주 전역 번호
    ↓
render/html.py      시맨틱 HTML   ← 결과물 본체
render/speech.py    음성 조각 배열
render/markdown.py  저장용
```

### OCR 과 AI 의 역할이 다르다

OCR 은 규칙 기반이라 지어내지 못한다. 대신 구조를 모른다.
AI 는 구조를 알지만 지어낸다.
그래서 AI 의 결과를 OCR 텍스트와 대조해 검증한다 (`guard.py`).
AI 가 말한 숫자가 OCR 에 없으면 `unverified_number` 로 표시하고,
본문 길이가 원문보다 많이 짧으면 요약으로 보고 `body_shrunk` 를 붙인다.

## 파일

| 파일 | 하는 일 | 담당 |
|---|---|---|
| `app/schema.py` | **전 모듈 공통 계약.** 여기부터 읽는다 | 공동 |
| `app/ingest.py` | PDF → 페이지 PNG | A |
| `app/ocr.py` | Tesseract 래퍼 | A |
| `app/heuristics.py` | LLM 없이 최소 결과 (오프라인 경로) | A |
| `app/llm/prompts.py` | 프롬프트 단일 원천 | B |
| `app/llm/backend_gemini.py` | Gemini 호출, 재시도와 모델 폴백 | B |
| `app/llm/adapter.py` | 캐시 → 온라인 → degraded 분기 | B |
| `app/llm/guard.py` | 요약·할루시네이션 검사 | B |
| `app/cache.py` | DB + snapshots 이중 기록 | B |
| `app/assemble.py` | 페이지들 → 문서 하나 | C |
| `app/render/*.py` | HTML · 음성 · 마크다운 | C |
| `app/jobs.py` | 파이프라인 오케스트레이션 | C |
| `app/main.py` | FastAPI | C |
| `web/index.html` | 업로드 화면 | C |
| `web/result.html` | 결과 화면 (읽기 · 비교 탭) | C |
| `web/library.html` | 보관함 | C |
| `web/a11y.css` | 세 화면 공통 스타일 | C |

## 지켜야 할 규칙

**AI 는 한 페이지 안에서 판단할 수 있는 것만 한다.**
페이지를 넘나드는 일(문단 병합, 각주 전역 번호)은 `assemble.py` 가 한다.
이 분리를 깨면 LLM 호출이 페이지 독립성을 잃고 캐시가 무효화된다.

**본문 텍스트는 AI 가 새로 쓰지 않는다.**
OCR 결과를 채택하고 명백한 글자 오인식만 고친다. AI 는 요약하고 윤색한다.

**`prompts.py` 를 고치면 `PROMPT_VERSION` 이 자동으로 바뀐다.**
캐시와 snapshots 가 전부 무효화되므로, 데모용 캐시 워밍 이후에는 고치지 않는다.

**어떤 실패도 파이프라인을 죽이지 않는다.**
한 페이지가 실패하면 그 페이지만 degraded 로 처리하고 끝까지 간다.

**HTML 태그가 곧 탐색 기능이다.**
제목 레벨을 건너뛰지 않고, 표는 진짜 `<table>` 로, 그림은 `<figure>` 로 낸다.
눈으로만 보이는 표시는 이 제품에서 존재하지 않는 표시다.

## 스크린리더로 확인하는 법

태그가 제대로 붙었는지는 눈으로 봐서는 알 수 없다. 직접 들어본다.

- 급할 때: 윈도우 내레이터 (`Ctrl + Windows + Enter`, 설치 불필요)
- 제대로: NVDA (무료, nvaccess.org)

결과 화면에서 확인할 것.

| 키 | 되어야 하는 동작 |
|---|---|
| H | 제목에서 제목으로 건너뛴다 |
| G | 그림으로 건너뛴다 |
| T | 표로 건너뛴다 |
| K | 각주 링크로 건너뛴다 |
| Ctrl+Alt+방향키 | 표 안에서 셀을 옮기며 행·열 머리글을 같이 읽는다 |
| Insert+F7 | 제목 목록 창이 뜬다 |

하나라도 안 되면 그 태그가 빠진 것이다.

음성 엔진과 스크린리더는 다르다. NVDA 는 자체 목소리가 없고 윈도우에
깔린 음성(Heami 등)을 빌려 쓴다. 결과 화면의 재생 버튼도 브라우저를 통해
같은 윈도우 음성을 쓴다. 따로 설치할 것이 없다.

## 데모 준비

**발표용 PDF 는 전날 미리 한 번 변환해 둔다.**
한 번 변환한 페이지는 `snapshots/` 에 저장되어 다음부터는 AI 를 부르지 않는다.
현장에서 처음 돌리면 페이지당 12초가 걸리고, API 가 혼잡하면 발표가 멈춘다.

업로드 화면의 "오프라인 전용" 을 고르면 저장된 결과만 쓴다.
인터넷이 아예 없어도 데모가 된다.

## 남은 일

- 재생기에서 그림·표로 바로 건너뛰는 수단이 없다.
  스크린리더(G, T)로는 가능하다. 문서 개요 목차에 그림·표를 넣으면 해결된다.
- 수식 읽기문의 품질이 낮다. `prompts.py` 의 수식 규칙을 손봐야 한다.
- 문장 중간에 그림이 끼어든 경우 문단을 잇지 않고 끊어 둔다.
- 좌우 비교 화면의 왼쪽(일반 OCR) 설명을 더 채워야 한다.
- 실제 대학 교재(OpenStax 등)로 아직 검증하지 않았다.
