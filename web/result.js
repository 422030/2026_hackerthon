// 결과 화면. 서버가 보낸 HTML 프래그먼트를 그대로 삽입한다.
// 제목 레벨을 JS 로 바꾸지 않는다. 서버가 이미 정규화했다.

const $ = (id) => document.getElementById(id);
const job = new URLSearchParams(location.search).get("job");

let segments = [];
let cursor = 0;
let playing = false;
let playbackRun = 0;
let segmentStarted = 0;
let segmentRate = 1;
let segmentOffsets = [0];
let announcementRun = 0;

function formatTime(seconds) {
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

function updatePlaybackProgress() {
  const total = segmentOffsets.at(-1);
  const start = segmentOffsets[cursor] ?? 0;
  const end = segmentOffsets[cursor + 1] ?? start;
  const position = playing
    ? Math.min(end, start + (performance.now() - segmentStarted) / 1000 * segmentRate)
    : start;
  const rate = Number($("rate").value);
  $("audio-progress").value = total ? position / total : 0;
  say($("audio-time"), `${formatTime(position / rate)} / ${formatTime(total / rate)} (예상)`);
}

function say(el, text) {
  if (el.textContent !== text) el.textContent = text;
}

// Final speech-only fallback for math not normalized by the server.
function normalizeMathForSpeech(value) {
  const names = {n:"엔",x:"엑스",a:"에이",b:"비",m:"엠",f:"에프"};
  const atom = v => names[v.toLowerCase()] || v;
  const supers = {"⁰":"0","¹":"1","²":"2","³":"3","⁴":"4","⁵":"5","⁶":"6","⁷":"7","⁸":"8","⁹":"9"};
  const power = (base, exponent) => atom(base) + "의 " +
    (exponent === "2" ? "제곱" : exponent === "3" ? "세제곱" : atom(exponent) + "승");
  const exponent = text => text
    .replace(/([a-zA-Z])([⁰¹²³⁴⁵⁶⁷⁸⁹]+)/g,
      (_, b, e) => power(b, [...e].map(c => supers[c]).join("")))
    .replace(/([a-zA-Z])\^\{?([a-zA-Z0-9]+)\}?/g, (_, b, e) => power(b, e));
  const readInner = text => exponent(text)
    .replace(/\b([2-9])\s*([nx])\b/gi, (_, c, v) => c + " " + atom(v))
    .replace(/\b([nx])\b/gi, (_, v) => atom(v));
  return exponent(value.replace(/(O|Ω|Θ)\s*\(\s*([^()]*)\s*\)/g,
    (_, kind, inner) => ({O:"빅오",Ω:"빅오메가",Θ:"빅세타"}[kind]) + " " + readInner(inner)))
    .replace(/\b([2-9])\s*([nx])(?=[가-힣\s.,;)]|$)/gi, (_, c, v) => c + " " + atom(v))
    .replace(/\b([nx])(?=[은는이가을를과와에의보다])/gi, (_, v) => atom(v))
    .replace(/∈/g, " 에 속한다 ").replace(/→/g, " 따라서 ")
    .replace(/\s+/g, " ").trim();
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
  segments = segments.map(segment => ({...segment, text: normalizeMathForSpeech(segment.text || "")}));

  for (const segment of segments) {
    const duration = Math.max(.5, Array.from(segment.text).length / 6);
    segmentOffsets.push(segmentOffsets.at(-1) + duration + (segment.pause_ms_after || 0) / 1000);
  }
  updatePlaybackProgress();


  $("baseline").textContent =
    (await (await fetch(`/api/jobs/${job}/baseline`)).text()) || "(없음)";
  $("ours").textContent = segments.map((x) => x.text).join("\n");

  announceShortcutHint();
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
    cursor = segments.length;
    stop();
    speakFeedback("끝까지 읽었습니다.");
    return;
  }
  const run = ++playbackRun;
  cursor = i;
  segmentStarted = performance.now();
  segmentRate = Number($("rate").value);
  updatePlaybackProgress();
  highlight(segments[i].block_id);

  const u = new SpeechSynthesisUtterance(segments[i].text);
  u.lang = segments[i].lang || "ko-KR";
  u.rate = segmentRate;
  u.onend = () => {
    if (!playing || run !== playbackRun) return;
    const wait = segments[i].pause_ms_after || 0;
    setTimeout(() => playing && run === playbackRun && speakFrom(i + 1), wait);
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

// 안내를 읽은 뒤 재생 중이었다면 현재 단락부터 이어 읽는다.
function speakFeedback(message, resume = false) {
  say($("speech-status"), message);
  if (!("speechSynthesis" in window)) return;
  const token = ++announcementRun;
  playbackRun++;
  speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(message);
  utterance.lang = "ko-KR";
  utterance.rate = 1;
  utterance.onend = () => {
    if (token === announcementRun && resume && playing) speakFrom(cursor);
  };
  speechSynthesis.speak(utterance);
}

function start() {
  if (!segments.length || !("speechSynthesis" in window)) return;
  speechSynthesis.cancel();
  if (cursor >= segments.length) cursor = 0;
  playing = true;
  $("play").setAttribute("aria-pressed", "true");
  speakFeedback("읽기를 시작합니다.", true);
}

function stop() {
  playing = false;
  announcementRun++;
  playbackRun++;
  speechSynthesis.cancel();
  updatePlaybackProgress();
  $("play").setAttribute("aria-pressed", "false");
}

function togglePlayback() {
  if (playing) {
    stop();
    speakFeedback("일시정지했습니다.");
  } else {
    start();
  }
}

$("play").addEventListener("click", () => {
  togglePlayback();
  // 재생 후에는 문서에 포커스를 두어 단축키를 바로 사용할 수 있게 한다.
  $("doc").focus({ preventScroll: true });
});

function moveParagraph(delta) {
  if (!segments.length) return;
  playbackRun++;
  speechSynthesis.cancel();
  const next = Math.max(0, Math.min(segments.length - 1, cursor + delta));
  cursor = next;
  highlight(segments[cursor]?.block_id);
  updatePlaybackProgress();
  speakFeedback(delta < 0 ? "이전" : "다음", playing);
}

$("prev").addEventListener("click", () => moveParagraph(-1));
$("next").addEventListener("click", () => moveParagraph(1));

function setRate(rate) {
  const value = Math.max(0.5, Math.min(2.5, Math.round(rate * 10) / 10));
  $("rate").value = value.toFixed(1);
  $("rate-out").textContent = `${value.toFixed(1)}배`;
  updatePlaybackProgress();
  speakFeedback(`${value.toFixed(1)}배.`, playing);
}

$("rate").addEventListener("input", (e) => setRate(Number(e.target.value)));

// 결과 화면의 키보드 음성 재생 조작. 폼 요소와 버튼의 기본 키 동작은 유지한다.
const SHORTCUT_HELP = "사용방법. 스페이스는 재생과 일시정지. 왼쪽과 오른쪽 화살표는 단락 이동. 위쪽과 아래쪽 화살표는 속도 조절. 숫자 영은 사용법 듣기. 이스케이프는 종료.";

const SHORTCUT_HINT = "숫자 영을 누르면 사용법을 들을 수 있습니다.";
let hintAnnounced = false;

// 결과 화면에 들어오자마자 단축키가 있다는 것부터 알린다.
// 브라우저가 사용자 조작 전의 음성을 막는 경우가 있어, 막혔으면 첫 조작 때 다시 알린다.
function announceShortcutHint() {
  if (hintAnnounced || !segments.length) return;
  say($("speech-status"), SHORTCUT_HINT);
  if (!("speechSynthesis" in window)) return;

  const utterance = new SpeechSynthesisUtterance(SHORTCUT_HINT);
  utterance.lang = "ko-KR";
  utterance.rate = 1;
  utterance.onstart = () => { hintAnnounced = true; };
  speechSynthesis.speak(utterance);

  setTimeout(() => {
    if (hintAnnounced) return;
    // 교재를 읽는 중이면 끊지 않는다.
    const retry = () => {
      if (playing || speechSynthesis.speaking || speechSynthesis.pending) return;
      announceShortcutHint();
    };
    document.addEventListener("keydown", retry, { once: true });
    document.addEventListener("click", retry, { once: true });
  }, 1200);
}

function announceHelp() {
  speakFeedback(SHORTCUT_HELP, playing);
}

document.addEventListener("keydown", (event) => {
  if (event.altKey || event.ctrlKey || event.metaKey || event.repeat) return;
  if ($("panel-read").hidden) return;
  const target = event.target;
  if (target instanceof Element &&
      target.closest("input, textarea, select, [contenteditable], [role='textbox']")) return;
  // 버튼과 링크의 Space/Enter 기본 동작은 유지한다.
  if ((event.key === " " || event.key === "Spacebar") &&
      target instanceof Element && target.closest("button, a, [role='button']")) return;
  if (!segments.length && event.key !== "?") return;

  switch (event.key) {
    case " ":
    case "Spacebar":
      event.preventDefault();
      togglePlayback();
      break;
    case "ArrowRight":
      event.preventDefault();
      $("next").click();
      break;
    case "ArrowLeft":
      event.preventDefault();
      $("prev").click();
      break;
    case "ArrowUp":
      event.preventDefault();
      setRate(Number($("rate").value) + 0.1);
      break;
    case "ArrowDown":
      event.preventDefault();
      setRate(Number($("rate").value) - 0.1);
      break;
    case "Home":
      event.preventDefault();
      playbackRun++;
      if ("speechSynthesis" in window) speechSynthesis.cancel();
      cursor = 0;
      highlight(segments[0]?.block_id);
      updatePlaybackProgress();
      speakFeedback("첫 단락으로 이동했습니다.", playing);
      break;
    case "0":
    case "?":
      event.preventDefault();
      announceHelp();
      break;
    case "Escape":
      if (playing || ("speechSynthesis" in window && speechSynthesis.speaking)) {
        event.preventDefault();
        stop();
        speakFeedback("음성 재생을 종료했습니다.");
      }
      break;
  }
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

setInterval(() => { if (playing) updatePlaybackProgress(); }, 250);
load();
