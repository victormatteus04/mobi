let groupsConfig = [];

function fmtBytes(n) {
  if (n === undefined || n === null) return "-";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(1)} ${units[i]}`;
}

function fmtElapsed(s) {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}m ${sec.toString().padStart(2, "0")}s`;
}

function dotClass(status) {
  if (!status || status.age_s === null || status.age_s === undefined) return "dead";
  if (status.age_s < 1.5) return "ok";
  if (status.age_s < 5) return "warn";
  return "bad";
}

async function loadConfig() {
  const res = await fetch("/api/config");
  const data = await res.json();
  groupsConfig = data.groups;

  const groupsEl = document.getElementById("groups");
  groupsEl.innerHTML = "";
  for (const g of groupsConfig) {
    const card = document.createElement("div");
    card.className = "group-card";
    card.id = `group-${g.name}`;
    const topics = [...g.required.map(t => [t, true]), ...g.optional.map(t => [t, false])];
    card.innerHTML = `<h3>${g.label}</h3>` + topics.map(([topic, required]) => `
      <div class="topic-row" data-topic="${topic}">
        <span class="dot"></span>
        <span class="topic-name">${topic}</span>
        <span class="topic-req">${required ? "obrigatório" : ""}</span>
        <span class="topic-rate">-</span>
      </div>`).join("");
    groupsEl.appendChild(card);
  }

  const checksEl = document.getElementById("group-checks");
  checksEl.innerHTML = "<legend>Grupos de sensores</legend>" + groupsConfig.map(g => `
    <label class="group-check">
      <input type="checkbox" value="${g.name}" ${g.name !== "d455" ? "checked" : ""}>
      ${g.label}
    </label>`).join("");
}

async function pollStatus() {
  try {
    const res = await fetch("/api/status");
    const status = await res.json();
    for (const [topic, st] of Object.entries(status)) {
      const row = document.querySelector(`.topic-row[data-topic="${CSS.escape(topic)}"]`);
      if (!row) continue;
      row.querySelector(".dot").className = `dot ${dotClass(st)}`;
      row.querySelector(".topic-rate").textContent =
        st.age_s === null ? "sem dado" : `${st.rate_hz} Hz`;
    }
  } catch (e) { /* backend ainda subindo */ }
}

function selectedGroups() {
  return [...document.querySelectorAll("#group-checks input:checked")].map(el => el.value);
}

async function pollRecordStatus() {
  try {
    const res = await fetch("/api/record/status");
    const st = await res.json();
    const idle = document.getElementById("record-idle");
    const active = document.getElementById("record-active");
    if (st.recording) {
      idle.classList.add("hidden");
      active.classList.remove("hidden");
      document.getElementById("rec-name").textContent = st.name;
      document.getElementById("rec-elapsed").textContent = fmtElapsed(st.elapsed_s);
      document.getElementById("rec-size").textContent = fmtBytes(st.size_bytes);
      document.getElementById("rec-log").textContent = (st.log || []).join("\n");
    } else {
      idle.classList.remove("hidden");
      active.classList.add("hidden");
    }
  } catch (e) { /* backend ainda subindo */ }
}

async function loadBags() {
  try {
    const res = await fetch("/api/bags");
    const bags = await res.json();
    const tbody = document.querySelector("#bags-table tbody");
    tbody.innerHTML = bags.map(b => `
      <tr>
        <td>${b.name}</td>
        <td>${fmtBytes(b.size_bytes)}</td>
        <td>${new Date(b.modified_at * 1000).toLocaleString("pt-BR")}</td>
      </tr>`).join("");
  } catch (e) { /* backend ainda subindo */ }
}

async function startRecording() {
  const name = document.getElementById("bag-name").value.trim();
  const groups = selectedGroups();
  const extraTopics = document.getElementById("extra-topics").value
    .split(",").map(s => s.trim()).filter(Boolean);
  const topicsOnly = document.getElementById("topics-only").checked;
  const operator = document.getElementById("meta-operator").value.trim();
  const location = document.getElementById("meta-location").value.trim();
  const conditions = document.getElementById("meta-conditions").value.trim();
  const notes = document.getElementById("meta-notes").value.trim();
  const msgEl = document.getElementById("start-message");
  msgEl.textContent = "iniciando...";
  const res = await fetch("/api/record/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name, groups, extra_topics: extraTopics, topics_only: topicsOnly,
      operator, location, conditions, notes,
    }),
  });
  const data = await res.json();
  msgEl.textContent = data.message;
  if (data.ok) pollRecordStatus();
}

async function stopRecording() {
  await fetch("/api/record/stop", { method: "POST" });
  pollRecordStatus();
  setTimeout(loadBags, 1000);
}

function tickClock() {
  document.getElementById("clock").textContent = new Date().toLocaleTimeString("pt-BR");
}

document.getElementById("btn-start").addEventListener("click", startRecording);
document.getElementById("btn-stop").addEventListener("click", stopRecording);

loadConfig().then(() => {
  pollStatus();
  setInterval(pollStatus, 1000);
});
pollRecordStatus();
setInterval(pollRecordStatus, 1000);
loadBags();
setInterval(loadBags, 4000);
tickClock();
setInterval(tickClock, 1000);
