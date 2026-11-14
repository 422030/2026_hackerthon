"""Gemini 백엔드. [담당: B]

무료 티어를 쓴다. 분당·일일 한도가 있으므로 동시성 1 로 호출하고
데모 전에 캐시를 미리 채운다.

키는 환경변수 GEMINI_API_KEY 또는 GOOGLE_API_KEY 에서 읽는다.
모델은 GEMINI_MODEL 로 바꿀 수 있다.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")

# 앞 모델이 막히면 순서대로 내려간다. 데모 중 503 으로 멈추지 않기 위한 장치다.
# lite 는 구조 해석이 약하지만, 빈 결과보다는 낫다.
FALLBACK_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]

# 응답이 오지 않는 호출을 끊는다. 제한이 없으면 그 페이지에서 변환이 영원히 멈춘다.
# 빽빽한 페이지는 90초를 넘기므로 넉넉하게 잡는다.
TIMEOUT_S = int(os.environ.get("GEMINI_TIMEOUT_S", "150"))


def api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def available() -> bool:
    return api_key() is not None


_CLIENT = None


def _client():
    """클라이언트를 한 번만 만든다. 호출마다 새로 만들면 응답을 다 읽기 전에 닫힌다."""
    global _CLIENT
    if _CLIENT is None:
        from google import genai
        from google.genai import types

        _CLIENT = genai.Client(
            api_key=api_key(),
            http_options=types.HttpOptions(timeout=TIMEOUT_S * 1000),
        )
    return _CLIENT


def list_models() -> list[str]:
    """키가 어떤 모델을 쓸 수 있는지 확인용. 모델명이 바뀌었을 때 쓴다."""
    try:
        names = []
        for m in _client().models.list():
            actions = getattr(m, "supported_actions", None) or []
            if not actions or "generateContent" in actions:
                names.append(m.name.replace("models/", ""))
        return names
    except Exception as exc:  # noqa: BLE001
        return [f"(조회 실패: {exc})"]


def generate(system: str, user_text: str, image_path: str | None) -> str:
    """시스템 지시 + 사용자 메시지 + 페이지 이미지를 보내고 JSON 문자열을 받는다.

    503(과부하)과 429(한도)는 일시적이다. 짧게 쉬었다 다시 부르고,
    같은 모델이 계속 막히면 FALLBACK_MODELS 를 순서대로 시도한다.

    TIMEOUT_S 를 넘긴 호출은 같은 모델로 다시 걸지 않고 다음 모델로 넘어간다.
    한 페이지가 모든 모델에서 막히면 예외를 올린다. 호출부가 degraded 로 받는다.
    """
    import time

    models = [DEFAULT_MODEL] + [m for m in FALLBACK_MODELS if m != DEFAULT_MODEL]
    last: Exception | None = None

    for model in models:
        for attempt in range(3):
            try:
                return _generate_once(model, system, user_text, image_path)
            except Exception as exc:  # noqa: BLE001
                last = exc
                if _is_timeout(exc):
                    break
                msg = str(exc)
                retryable = "503" in msg or "429" in msg or "UNAVAILABLE" in msg
                if not retryable:
                    break
                time.sleep(2 * (attempt + 1))
    raise last if last else RuntimeError("호출 실패")


def _is_timeout(exc: Exception) -> bool:
    """클라이언트가 끊은 경우와 서버가 504 로 끊은 경우를 함께 본다."""
    text = f"{type(exc).__name__} {exc}".lower()
    return (
        "timeout" in text
        or "timed out" in text
        or "504" in text
        or "deadline_exceeded" in text
    )


def _generate_once(
    model: str, system: str, user_text: str, image_path: str | None
) -> str:
    from google.genai import types

    parts: list = []
    if image_path:
        img = Path(image_path)
        if img.exists() and img.stat().st_size < 15_000_000:
            mime = "image/png" if img.suffix.lower() == ".png" else "image/jpeg"
            parts.append(types.Part.from_bytes(data=img.read_bytes(), mime_type=mime))
    parts.append(types.Part.from_text(text=user_text))

    resp = _client().models.generate_content(
        model=model,
        contents=parts,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            temperature=0.2,
        ),
    )
    return resp.text or ""


def parse_json(raw: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip())
    return json.loads(text)
