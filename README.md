# 전공 교재 음성 변환기

> **시각장애 학생의 전공 교재 접근성을 높이기 위한 AI 기반 PDF 변환 프로젝트**  
> 2026 해커톤 · 로컬 실행형 프로토타입

일반 PDF나 이미지로 제공되는 대학 전공 교재는 표, 그림, 수식, 문서 구조가 음성 읽기에서 충분히 전달되지 않을 수 있습니다. 이 프로젝트는 교재를 **구조화된 HTML 문서**와 **브라우저 음성 재생용 텍스트**로 변환하여, 내용을 탐색하고 들을 수 있도록 돕습니다.

## 주요 기능

- **PDF·이미지 입력**: PDF, PNG, JPG, JPEG 업로드 및 PDF 페이지 범위 선택
- **문서 구조 분석**: 제목, 본문, 목록, 그림, 표, 수식 등 블록 단위로 구성
- **AI 기반 시각 자료 설명**: 그림과 표의 내용을 읽기 위한 설명 생성
- **수식 음성 보정**: 지수·아래첨자·분수·루트, 일부 점근 표기법(빅오·빅오메가·빅세타) 등 한국어 읽기 보정
- **음성 재생 및 탐색**: 브라우저 Web Speech API를 이용한 재생·일시정지, 단락 이동, 속도 조절
- **접근성 UI**: 키보드 조작, 읽는 위치 강조, 문서 제목과 페이지 안내
- **일반 OCR 비교**: 일반 OCR 텍스트와 변환 결과를 화면에서 나란히 확인
- **변환 관리**: 진행 상태 확인, 중단 요청, 설명 생성에 실패한 페이지 재시도

> 일반 OCR 비교 영역은 **시각적 비교용**입니다. 음성 재생은 변환 결과 화면에서 제공합니다.

## 처리 흐름

```text
PDF / 이미지 업로드
        ↓
PDF 페이지 이미지화 (PyMuPDF)
        ↓
원본 텍스트층 추출 또는 OCR (Tesseract)
        ↓
AI 페이지 분석 (Gemini 우선, 설정에 따라 Claude)
        ↓
OCR 대조 및 문서 블록 조립
        ↓
접근성 HTML + 음성 재생 세그먼트 생성
        ↓
브라우저에서 탐색 및 음성 재생
```

- PDF 페이지는 최대 **2페이지씩 병렬 분석**합니다.
- 동일한 페이지 이미지·모델·프롬프트 버전의 AI 분석 결과는 캐시할 수 있습니다.
- 한 번의 변환 요청에서 **최대 20페이지**를 처리합니다.
- 외국어·전문용어 목록을 별도로 생성하는 기능은 제거되어 있습니다.

## 기술 스택

| 구분 | 기술 |
| --- | --- |
| 백엔드 | Python 3.11+, FastAPI, Uvicorn, Pydantic |
| PDF 처리 | PyMuPDF |
| OCR | Tesseract OCR, pytesseract, Pillow, OpenCV |
| AI | Google Gemini API, Anthropic Claude API 관련 코드 |
| 프론트엔드 | HTML, CSS, JavaScript |
| 음성 재생 | 브라우저 Web Speech API |
| 데이터 저장 | SQLite 기반 작업·페이지·캐시 저장 |

## 실행 방법

### 1. 저장소 내려받기

```bash
git clone https://github.com/422030/2026_hackerthon.git
cd 2026_hackerthon
```

### 2. Python 환경 구성

Python **3.11 이상**이 필요합니다.

**Windows PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### 3. Tesseract OCR 설치

이미지 기반 PDF와 스캔 문서를 처리하려면 **Tesseract OCR 본체**와 한국어·영어 언어 데이터(`kor`, `eng`)가 필요합니다. `pytesseract`만 설치하는 것으로는 충분하지 않습니다.

- Windows: Tesseract 설치 후 실행 파일이 PATH에서 인식되는지 확인
- macOS / Linux: 운영체제의 패키지 관리자로 Tesseract와 한국어 언어 데이터 설치
- 확인: `tesseract --version`, `tesseract --list-langs`

텍스트층이 있는 PDF는 해당 텍스트를 우선 활용합니다.

### 4. AI API 키 설정

**Windows PowerShell**

```powershell
$env:GEMINI_API_KEY = "본인의_API_키"
```

**macOS / Linux**

```bash
export GEMINI_API_KEY="본인의_API_키"
```

코드는 `GOOGLE_API_KEY`도 확인하며, Gemini를 사용할 수 없는 경우 `ANTHROPIC_API_KEY` 설정을 확인합니다. **실제 API 키를 GitHub에 커밋하지 마세요.** AI 연결이 없으면 일반적인 교재 변환이 정상적으로 진행되지 않습니다.

### 5. 서버 실행

```bash
python -m uvicorn app.main:app --port 8010
```

브라우저에서 **http://localhost:8010** 접속.

서버 종료는 실행 중인 터미널에서 `Ctrl + C`입니다.

## 사용 방법

1. 첫 화면에서 교재 PDF 또는 이미지 파일을 선택합니다.
2. PDF라면 변환할 시작·끝 페이지를 지정합니다(한 번에 최대 20쪽).
3. **변환 시작**을 누르고 진행 상태를 확인합니다.
4. 완료 후 결과 화면에서 문서를 읽거나 음성으로 재생합니다.
5. 필요하면 **일반 OCR과 비교**를 눌러 두 결과를 확인합니다.
6. 일부 페이지의 AI 설명이 실패한 경우 **실패한 쪽만 다시 변환**을 사용할 수 있습니다.

## 음성 재생 단축키

| 키 | 기능 |
| --- | --- |
| `Space` | 재생 / 일시정지 |
| `←` / `→` | 이전 / 다음 단락 |
| `↑` / `↓` | 읽기 속도 조절 |
| `Home` | 처음부터 |
| `?` | 단축키 음성 안내 |
| `Esc` | 음성 재생 종료 |

방향키로 단락을 이동하면 **“이전” / “다음”**처럼 짧게 음성 피드백을 제공합니다. 입력창과 버튼 등에서는 기본 키 동작을 우선하도록 구성되어 있습니다.

## 프로젝트 구조

```text
app/
  main.py             # FastAPI 라우트 및 정적 파일 제공
  jobs.py             # 변환 작업, 병렬 처리, 재시도 및 상태 관리
  ingest.py           # PDF/이미지 입력과 페이지 이미지화
  ocr.py              # 텍스트층 추출 및 Tesseract OCR
  assemble.py         # 페이지 분석 결과를 문서로 조립
  schema.py           # 데이터 모델
  llm/
    adapter.py        # AI 백엔드 선택, 분석 및 캐시 연계
    prompts.py        # 문서 분석 프롬프트
  render/
    html.py           # 접근성 HTML 생성
    speech.py         # 음성 세그먼트 및 수식 읽기 보정
web/
  index.html          # 파일 업로드 화면
  upload.js           # 업로드 및 진행 상태
  result.html         # 변환 결과 화면
  result.js           # 음성 재생·단축키·최종 수식 보정
  a11y.css            # 접근성 스타일
requirements.txt
```

## 주요 API

| 메서드 | 경로 | 용도 |
| --- | --- | --- |
| GET | `/api/health` | AI 백엔드 상태 |
| POST | `/api/jobs` | 변환 작업 시작 |
| GET | `/api/jobs/{job_id}` | 진행 상태 조회 |
| POST | `/api/jobs/{job_id}/cancel` | 변환 중단 요청 |
| POST | `/api/jobs/{job_id}/retry` | 실패 페이지 재변환 |
| GET | `/api/jobs/{job_id}/doc` | 구조화된 문서 데이터 |
| GET | `/api/jobs/{job_id}/html` | 변환 HTML |
| GET | `/api/jobs/{job_id}/speech` | 음성 세그먼트 |
| GET | `/api/jobs/{job_id}/baseline` | 비교용 일반 OCR 텍스트 |

## 현재 한계 및 유의사항

- **프로토타입**으로, 로컬 실행을 전제로 합니다. 외부 공개 서비스용 인증·보안·운영 체계를 갖춘 상태로 간주하면 안 됩니다.
- 수식 읽기 보정은 **일부 표기법에 대한 규칙 기반 처리**입니다. 복잡한 수식, 잘못 인식된 문자, 수식 문맥에 따라 읽기가 부정확할 수 있습니다.
- 그림·표 설명은 AI 분석 결과이므로 원문과 반드시 일치한다고 보장할 수 없습니다. 중요 수치와 수식은 원문 대조가 필요합니다.
- 처리 시간은 PDF 구성, 페이지 수, OCR 필요 여부, AI API 응답에 따라 달라집니다.
- 음성 품질과 지원 기능은 브라우저 및 운영체제의 TTS 음성에 따라 달라질 수 있습니다.
- 이 README는 **GitHub `main` 브랜치의 소스코드 기준**으로 작성되었으며, 모든 기능의 실기기·스크린리더 테스트 완료를 의미하지 않습니다.

## 프로젝트 목표

단순히 PDF 문자를 추출하는 데서 끝나지 않고, **시각적 정보와 문서 구조를 음성으로 탐색할 수 있도록 전달**하는 것이 목표입니다. 향후 실제 시각장애 사용자 테스트와 수식·도표 읽기 정확도 검증을 통해 접근성을 개선할 수 있습니다.
