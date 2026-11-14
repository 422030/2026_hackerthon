// 업로드 화면 동작. 진행 상황은 1초 폴링으로 받는다.
// aria-live 영역은 문장이 실제로 바뀔 때만 갱신한다. 매번 쓰면 스크린리더가 계속 떠든다.

const $ = (id) => document.getElementById(id);
const STAGE_KO = {
  ingest: "파일 읽는 중",
  ocr: "글자 인식 중",
  analyze: "내용 해석 중",
  assemble: "문서 구성 중",
  render: "마무리 중",
  idle: "준비 중",
};

let lastStatusText = "";
let currentJob = null;

/** 변환 중단. 돌고 있는 쪽은 끝까지 간다. AI 호출 한가운데를 끊을 수단이 없다. */
$("stop").addEventListener("click", async () => {
  if (!currentJob) return;
  $("stop").disabled = true;
  const msg = "멈추는 중입니다. 지금 변환하는 쪽이 끝나면 멈춥니다.";
  say($("progress"), msg);
  speak(msg);
  try {
    const response = await fetch(`/api/jobs/${currentJob}/cancel`, { method: "POST" });
    if (!response.ok) throw new Error();
  } catch {
    $("stop").disabled = false;
    say($("progress"), "중단을 요청하지 못했습니다. 다시 시도해 주세요.");
  }
});

function resetForm() {
  $("start").disabled = false;
  $("start").textContent = "변환 시작";
  $("conversion-panel").hidden = true;
  $("form").hidden = false;
  $("start").focus();
  currentJob = null;
}

const SEC_PER_PAGE = 60;
const MAX_PAGES = 20;

/** aria-live 영역 갱신. 같은 문장이면 건드리지 않는다. */
function say(el, text) {
  if (el.textContent === text) return;
  el.textContent = text;
}

/** 변환 상태를 음성으로 안내한다. */
function speak(text) {
  if (!("speechSynthesis" in window)) return;
  try {
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "ko-KR";
    speechSynthesis.speak(u);
  } catch {
    /* 음성 엔진이 없는 환경 */
  }
}

/** 범위를 고칠 때마다 쪽 수와 예상 시간을 알린다. */
function updateEstimate(announce) {
  const from = parseInt($("page-from").value, 10);
  const to = parseInt($("page-to").value, 10);
  if (!from || !to || to < from) {
    say($("estimate"), "");
    return;
  }

  const asked = to - from + 1;
  const pages = Math.min(asked, MAX_PAGES);
  const minutes = Math.max(1, Math.round((pages * SEC_PER_PAGE) / 60));

  let text = `총 ${pages}쪽. 약 ${minutes}분 소요됩니다.`;
  if (asked > MAX_PAGES) {
    text += ` 한 번에 ${MAX_PAGES}쪽까지만 변환하므로 ${asked - pages}쪽은 빠집니다.`;
  }
  say($("estimate"), text);
  if (announce) speak(text);
}

$("page-from").addEventListener("change", () => updateEstimate(true));
$("page-to").addEventListener("change", () => updateEstimate(true));
$("page-from").addEventListener("input", () => updateEstimate(false));
$("page-to").addEventListener("input", () => updateEstimate(false));
updateEstimate(false);

$("file").addEventListener("change", (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const mb = (f.size / 1024 / 1024).toFixed(1);
  const msg = `선택됨: ${f.name}, 크기 ${mb}메가바이트`;
  say($("file-info"), msg);
  speak(msg);
});

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("start");
  const err = $("error");
  err.hidden = true;

  btn.disabled = true;
  btn.textContent = "변환 중...";
  lastStatusText = "";
  say($("progress"), "");

  try {
    const fd = new FormData($("form"));
    const r = await fetch("/api/jobs", { method: "POST", body: fd });
    if (!r.ok) throw new Error(`서버 응답 ${r.status}`);
    const info = await r.json();
    currentJob = info.job_id;
    $("form").hidden = true;
    $("stop").disabled = false;
    $("conversion-panel").hidden = false;
    $("conversion-title").focus();
    if (info.capped) {
      const msg =
        `${info.max_pages}쪽까지만 변환합니다. ` +
        `${info.page_from}쪽부터 ${info.page_to}쪽까지 처리합니다.`;
      say($("progress"), msg);
      speak(msg);
    } else {
      speak("변환을 시작합니다.");
    }
    await poll(info.job_id);
  } catch (ex) {
    err.hidden = false;
    err.textContent = `변환을 시작하지 못했습니다. ${ex.message}`;
    resetForm();
  }
});

async function poll(jobId) {
  let fails = 0;

  for (;;) {
    await new Promise((res) => setTimeout(res, 1000));

    let st;
    try {
      const r = await fetch(`/api/jobs/${jobId}`);
      if (!r.ok) throw new Error(`서버 응답 ${r.status}`);
      st = await r.json();
      fails = 0;
    } catch {
      if (++fails >= 3) {
        $("error").hidden = false;
        $("error").textContent = "서버와 연결이 끊겼습니다. 다시 시도해 주세요.";
        resetForm();
        return;
      }
      continue;
    }

    const stage = STAGE_KO[st.stage] || st.stage;
    const text =
      st.pages_total > 0
        ? `${st.pages_total}쪽 중 ${st.pages_done}쪽 처리함. 단계: ${stage}`
        : `단계: ${stage}`;
    if (text !== lastStatusText) {
      lastStatusText = text;
      say($("progress"), text);
      // 쪽마다 읽으면 말이 끊이지 않는다. 다섯 쪽마다 한 번만 알린다.
      if (st.pages_done > 0 && st.pages_done % 5 === 0) {
        speak(`${st.pages_total}쪽 중 ${st.pages_done}쪽 처리했습니다.`);
      }
    }

    if (st.status === "done") {
      say($("progress"), "변환 완료. 결과 화면으로 이동합니다.");
      speak("변환이 끝났습니다. 결과 화면으로 이동합니다.");
      setTimeout(() => {
        location.href = `/result.html?job=${jobId}`;
      }, 350);
      return;
    }

    if (st.status === "cancelled") {
      resetForm();
      if (st.pages_done > 0) {
        const msg = `${st.pages_done}쪽까지 변환하고 멈췄습니다. 그만큼은 결과로 볼 수 있습니다.`;
        say($("progress"), msg);
        speak(msg);
        setTimeout(() => {
          location.href = `/result.html?job=${jobId}`;
        }, 1200);
      } else {
        const msg = "변환을 멈췄습니다. 처리한 쪽이 없습니다.";
        say($("progress"), msg);
        speak(msg);
      }
      return;
    }

    if (st.status === "error") {
      $("error").hidden = false;
      $("error").textContent = `변환에 실패했습니다. ${st.error || ""}`;
      speak("변환에 실패했습니다.");
      resetForm();
      $("error").focus?.();
      return;
    }
  }
}

