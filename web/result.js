// 결과 화면. 서버가 보낸 HTML 프래그먼트를 그대로 삽입한다.
// 제목 레벨을 JS 로 바꾸지 않는다. 서버가 이미 정규화했다.

const $ = (id) => document.getElementById(id);
const job = new URLSearchParams(location.search).get("job");

let segments = [];
let cursor = 0;
let playing = false;

function say(el, text) {
  if (el.textContent !== text) el.textContent = text;
}

/** 내려받는 파일 이름. 책이름_시작쪽-끝쪽. 서버가 보내는 이름과 같은 규칙이다. */
function downloadName(doc, ext) {
  let stem = String(doc.source_filename || "교재").replace(/(\.[^.]+)+$/, "");
  stem = stem.replace(/[\\/:*?"<>|]+/g, "_").trim() || "교재";
  const [first, last] = doc.page_range || [1, 1];
  return `${stem}_${first}-${last}.${ext}`;
}

async function load() {
  if (!job) {
    say($("doc-summary"), "job 값이 없습니다. 업로드 화면에서 다시 시작해 주세요.");
    return;
  }

  const doc = await (await fetch(`/api/jobs/${job}/doc`)).json();
  document.title = `${doc.title} — 변환 결과`;
  $("doc-title").textContent = doc.title || "변환 결과";

  const s = doc.stats || {};
  let summary =
    `총 ${s.pages || 0}쪽. 그림 ${s.figures || 0}개, 표 ${s.tables || 0}개, ` +
    `수식 ${s.formulas || 0}개.`;
  if ((doc.degraded_pages || []).length) {
    summary += ` ${doc.degraded_pages.join(", ")}쪽은 AI 설명을 생성하지 못했습니다.`;
  }
  say($("doc-summary"), summary);
  showRetry(doc.degraded_pages || []);
  $("ours-summary").textContent =
    `제목 ${s.headings || 0}개, 그림 ${s.figures_described || 0}개 설명됨.`;

  const html = await (await fetch(`/api/jobs/${job}/html`)).text();
  $("doc").insertAdjacentHTML("beforeend", html);

  segments = await (await fetch(`/api/jobs/${job}/speech`)).json();

  $("dl-md").href = `/api/jobs/${job}/markdown`;
  $("dl-md").download = downloadName(doc, "md");
  $("dl-html").href = `/api/jobs/${job}/download.html`;
  $("dl-html").download = downloadName(doc, "html");

  $("baseline").textContent =
    (await (await fetch(`/api/jobs/${job}/baseline`)).text()) || "(없음)";
  $("ours").textContent = segments.map((x) => x.text).join("\n");
}

// ── 실패한 쪽 다시 변환 ────────────────────────────────
// 전체를 다시 올리지 않는다. 성공한 쪽은 저장된 결과를 그대로 쓴다.

function showRetry(degraded) {
  if (!degraded.length) return;
  $("retry-msg").textContent =
    `${degraded.join(", ")}쪽은 도표 설명을 만들지 못했습니다.`;
  $("retry-box").hidden = false;
}

$("retry").addEventListener("click", async () => {
  const btn = $("retry");
  btn.disabled = true;
  say($("retry-status"), "다시 변환을 시작합니다.");

  try {
    const r = await fetch(`/api/jobs/${job}/retry`, { method: "POST" });
    if (!r.ok) throw new Error((await r.json()).error || `서버 응답 ${r.status}`);
    await pollRetry();
  } catch (ex) {
    btn.disabled = false;
    say($("retry-status"), `다시 변환하지 못했습니다. ${ex.message}`);
  }
});

async function pollRetry() {
  for (;;) {
    await new Promise((res) => setTimeout(res, 1500));
    const st = await (await fetch(`/api/jobs/${job}`)).json();

    if (st.status === "done") {
      say($("retry-status"), "다시 변환했습니다. 결과를 새로 불러옵니다.");
      location.reload();
      return;
    }
    if (st.status === "error") {
      $("retry").disabled = false;
      say($("retry-status"), `실패했습니다. ${st.error || ""}`);
      return;
    }
    say(
      $("retry-status"),
      `${st.pages_total}쪽 중 ${st.pages_done}쪽 처리함.`
    );
  }
}

// ── 음성 재생 ───────────────────────────────────────────
// 조각을 하나씩 넣는다. 전부 한 번에 넣으면 중간 이동과 정지가 불가능하다.

function speakFrom(i) {
  if (i >= segments.length) {
    stop();
    say($("speech-status"), "끝까지 읽었습니다.");
    return;
  }
  cursor = i;
  highlight(segments[i].block_id);

  const u = new SpeechSynthesisUtterance(segments[i].text);
  u.lang = segments[i].lang || "ko-KR";
  u.rate = parseFloat($("rate").value);
  u.onend = () => {
    if (!playing) return;
    const wait = segments[i].pause_ms_after || 0;
    setTimeout(() => playing && speakFrom(i + 1), wait);
  };
  speechSynthesis.speak(u);
}

function highlight(blockId) {
  document.querySelectorAll(".reading").forEach((el) => {
    el.classList.remove("reading");
    el.removeAttribute("aria-current");
  });
  const el = document.getElementById(blockId);
  if (el) {
    el.classList.add("reading");
    el.setAttribute("aria-current", "true");
  }
}

function start() {
  if (!segments.length) return;
  playing = true;
  $("play").setAttribute("aria-pressed", "true");
  say($("speech-status"), "읽기를 시작합니다.");
  speakFrom(cursor);
}

function stop() {
  playing = false;
  speechSynthesis.cancel();
  $("play").setAttribute("aria-pressed", "false");
}

$("play").addEventListener("click", () => {
  if (playing) {
    stop();
    say($("speech-status"), "일시정지했습니다.");
  } else {
    start();
  }
});

$("prev").addEventListener("click", () => {
  speechSynthesis.cancel();
  cursor = Math.max(0, cursor - 1);
  if (playing) speakFrom(cursor);
  else highlight(segments[cursor]?.block_id);
});

$("next").addEventListener("click", () => {
  speechSynthesis.cancel();
  cursor = Math.min(segments.length - 1, cursor + 1);
  if (playing) speakFrom(cursor);
  else highlight(segments[cursor]?.block_id);
});

$("rate").addEventListener("input", (e) => {
  $("rate-out").textContent = `${e.target.value}배`;
});

// ── 탭 ─────────────────────────────────────────────────
$("tab-compare").addEventListener("click", (event) => {
  const button = event.currentTarget;
  const showComparison = button.getAttribute("aria-expanded") === "false";
  button.setAttribute("aria-expanded", String(showComparison));
  button.textContent = showComparison ? "변환 결과로 돌아가기" : "일반 OCR과 비교";
  $("panel-read").hidden = showComparison;
  $("panel-compare").hidden = !showComparison;
});

load();
