// 보관함 목록. 같은 교재의 변환을 한 묶음으로 보여준다.

const esc = (s) =>
  String(s ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]
  );

/** 파일 이름에서 책 이름만 남긴다. '....pdf.pdf' 처럼 겹친 확장자도 뗀다. */
function bookName(filename) {
  return String(filename || "교재").replace(/(\.[^.]+)+$/, "") || "교재";
}

/** 내려받는 파일 이름. 책이름_시작쪽-끝쪽. 서버가 보내는 이름과 같은 규칙이다. */
function downloadName(it, ext) {
  const stem = bookName(it.filename).replace(/[\\/:*?"<>|]+/g, "_").trim() || "교재";
  const [first, last] = it.page_range || [1, 1];
  return `${stem}_${first}-${last}.${ext}`;
}

function when(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return `${d.getFullYear()}.${d.getMonth() + 1}.${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function rangeLabel(it) {
  const [first, last] = it.page_range || [1, 1];
  return first === last ? `${first}쪽` : `${first}–${last}쪽`;
}

function entry(it) {
  const s = it.stats || {};
  const parts = [];
  if (s.figures) parts.push(`그림 ${s.figures}개`);
  if (s.tables) parts.push(`표 ${s.tables}개`);
  if (s.formulas) parts.push(`수식 ${s.formulas}개`);
  if (s.footnotes) parts.push(`각주 ${s.footnotes}개`);

  const warn = (it.degraded || []).length
    ? `<p class="meta">${it.degraded.join(", ")}쪽은 그림 설명이 없습니다.</p>`
    : "";

  const label = `${bookName(it.filename)} ${rangeLabel(it)}`;

  return `
    <article class="item" id="item-${esc(it.job_id)}">
      <h4><a href="/result.html?job=${esc(it.job_id)}">${esc(rangeLabel(it))}</a></h4>
      <p class="meta">${esc(parts.join(" · "))}${parts.length ? " · " : ""}${esc(when(it.created_at))}</p>
      ${warn}
      <p class="actions">
        <a href="/result.html?job=${esc(it.job_id)}">읽기</a>
        <a href="/api/jobs/${esc(it.job_id)}/download.html"
           download="${esc(downloadName(it, "html"))}">HTML</a>
        <a href="/api/jobs/${esc(it.job_id)}/markdown"
           download="${esc(downloadName(it, "md"))}">마크다운</a>
        <button type="button" class="danger" data-del="${esc(it.job_id)}"
                aria-label="${esc(label)} 삭제">삭제</button>
      </p>
    </article>`;
}

/** 같은 책의 변환을 한 묶음으로. 묶음 안에서는 앞쪽부터 보여준다. */
function group(name, items) {
  const sorted = items
    .slice()
    .sort((a, b) => (a.page_range || [0])[0] - (b.page_range || [0])[0]);
  const id = `book-${name.replace(/[^a-zA-Z0-9가-힣]/g, "-")}`;

  return `
    <section class="book" aria-labelledby="${esc(id)}">
      <h3 id="${esc(id)}">${esc(name)}</h3>
      <p class="meta">변환 ${sorted.length}건</p>
      ${sorted.map(entry).join("")}
    </section>`;
}

async function remove(jobId, btn) {
  const article = document.getElementById(`item-${jobId}`);
  const label = btn.getAttribute("aria-label").replace(" 삭제", "");
  if (!confirm(`'${label}' 을(를) 보관함에서 지웁니다. 되돌릴 수 없습니다.`)) return;

  btn.disabled = true;
  try {
    const r = await fetch(`/api/jobs/${jobId}`, { method: "DELETE" });
    if (!r.ok) throw new Error(`서버 응답 ${r.status}`);
    focusAfterDelete(article);
    const book = article.closest(".book");
    article.remove();
    // 그 책의 마지막 변환이면 묶음째 사라진다.
    if (book && !book.querySelector(".item")) book.remove();
    const left = document.querySelectorAll(".item").length;
    document.getElementById("status").textContent = left
      ? `${label} 을(를) 지웠습니다. 남은 변환 ${left}건`
      : `${label} 을(를) 지웠습니다. 보관함이 비었습니다.`;
  } catch (ex) {
    btn.disabled = false;
    document.getElementById("status").textContent = `지우지 못했습니다. ${ex.message}`;
  }
}

/** 삭제 후 포커스가 사라지면 스크린리더 사용자는 현재 위치를 잃는다. */
function focusAfterDelete(article) {
  const all = [...document.querySelectorAll("button[data-del]")];
  const here = all.indexOf(article.querySelector("button[data-del]"));
  const next = all[here + 1] || all[here - 1] || document.getElementById("status");
  next?.focus();
}

document.getElementById("list").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-del]");
  if (btn) remove(btn.dataset.del, btn);
});

async function load() {
  const status = document.getElementById("status");
  try {
    const items = await (await fetch("/api/library")).json();
    if (!items.length) {
      status.textContent = "아직 변환한 교재가 없습니다.";
      return;
    }

    const books = new Map();
    for (const it of items) {
      const name = bookName(it.filename);
      if (!books.has(name)) books.set(name, []);
      books.get(name).push(it);
    }

    status.textContent = `교재 ${books.size}권, 변환 ${items.length}건`;
    document.getElementById("list").innerHTML = [...books]
      .map(([name, list]) => group(name, list))
      .join("");
  } catch (ex) {
    status.textContent = `목록을 불러오지 못했습니다. ${ex.message}`;
  }
}

load();
