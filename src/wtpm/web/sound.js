"use strict";

const TEXT_KEY = "wtpm.sound.text";
const DEFAULT_TEXT = `Der leise Fluss trägt Steine.
Der unruhige Ozean trägt Schiffe.

Am Ufer steht ein alter Mann,
er zählt die Wellen, zählt sie kaum.

Die Steine ruhn im kühlen Grund.`;

const LAYERS = {
  puls: { label: "Puls", key: "A" },
  bass: { label: "Bass", key: "B" },
  motiv: { label: "Motiv", key: "C" },
  boegen: { label: "Bögen", key: "D" },
  leitwort: { label: "Leitwörter", key: "E" },
};

const el = (id) => document.getElementById(id);
const pad2 = (n) => String(n).padStart(2, "0");

const state = {
  text: "",
  tokens: new Map(),
  score: null,
  strudel: null,
  hits: new Map(),
  amplitude: [],
  playing: false,
  clock: { cps: 1, anchor: 0, cycle: 0 },
  slots: 0,
  frame: null,
  slot: null,
  muted: new Set(),
  sampleSeed: null,
  bpm: null,
  tempoTimer: null,
  ready: null,
};

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

async function post(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || response.statusText);
  return body;
}

function setStatus(id, text, isError = false) {
  const status = el(id);
  status.classList.toggle("error", isError);
  status.textContent = text;
}

const soundStatus = (text, isError) => setStatus("soundStatus", text, isError);

function startStrudel() {
  state.ready = fetch("/api/samples")
    .then((response) => response.json())
    .then(({ base, map }) => initStrudel({ prebake: () => samples(map, base) }));
}

async function analyze() {
  state.text = el("text").value;
  localStorage.setItem(TEXT_KEY, state.text);
  setStatus("status", "analysiere …");
  await refreshSound();
}

async function refreshSound() {
  try {
    const payload = await post("/api/sonify", { text: state.text, sample_seed: state.sampleSeed });
    state.tokens = new Map(payload.analysis.tokens.map((token) => [token.id, token]));
    setStatus("status", `${payload.analysis.tokens.length} TOKENS · ${payload.analysis.sentences.length} SÄTZE`);
    state.score = payload.score;
    state.strudel = payload.strudel;
    state.sampleSeed = payload.score.sample_seed;
    el("sampleSeed").value = payload.score.sample_seed;
    el("play").disabled = false;
    el("reroll").disabled = false;
    renderTempo();
    render();
    if (state.playing) await play();
  } catch (error) {
    state.score = null;
    el("play").disabled = true;
    setStatus("status", error.message, true);
  }
}

function currentCps() {
  return (state.bpm ?? state.score.tempo.bpm) / 60 / state.score.tempo.beats_per_bar;
}

function strudelCode() {
  const voices = state.strudel.voices.filter((voice) => !state.muted.has(voice.layer));
  if (!voices.length) return null;
  return `setcps(${currentCps()})\nstack(\n  ${voices.map((voice) => voice.code).join(",\n  ")}\n).slow(${state.strudel.bars})`;
}

function cycleNow() {
  const { cps, anchor, cycle } = state.clock;
  return cycle + (Date.now() / 1000 - anchor) * cps;
}

async function play() {
  const code = strudelCode();
  if (!code) {
    await stop();
    soundStatus("alle Spuren stumm");
    return;
  }
  soundStatus("lädt Samples …");
  try {
    await state.ready;
    const now = Date.now() / 1000;
    state.clock = { cps: currentCps(), anchor: now, cycle: state.playing ? cycleNow() : 0 };
    await evaluate(code);
    Object.assign(state, { playing: true, slots: state.score.bars * state.score.tempo.steps_per_bar, slot: null });
    el("stop").disabled = false;
    document.body.classList.add("playing");
    soundStatus(state.muted.size ? `spielt · stumm: ${[...state.muted].map((n) => LAYERS[n].key).join("")}` : "spielt");
    animate();
  } catch (error) {
    state.playing = false;
    soundStatus(error.message, true);
  }
}

async function stop() {
  state.playing = false;
  cancelAnimationFrame(state.frame);
  highlightSlot(null);
  el("stop").disabled = true;
  document.body.classList.remove("playing");
  hush();
  soundStatus("gestoppt");
}

function togglePlay() {
  if (state.playing) stop();
  else if (state.score) play();
}

function toggleLayer(name) {
  if (state.muted.has(name)) state.muted.delete(name);
  else state.muted.add(name);
  for (const pad of document.querySelectorAll(`[data-layer="${name}"]`)) {
    pad.classList.toggle("muted", state.muted.has(name));
  }
  if (state.playing) play();
}

function animate() {
  cancelAnimationFrame(state.frame);
  const tick = () => {
    if (!state.playing) return;
    const perCycle = state.score.tempo.steps_per_bar;
    highlightSlot(Math.floor(cycleNow() * perCycle) % state.slots);
    state.frame = requestAnimationFrame(tick);
  };
  tick();
}

const TEMPO = { min: 40, max: 200 };

function textBpm() {
  return state.score?.tempo.bpm;
}

function renderTempo() {
  const knob = el("tempo");
  const bpm = state.bpm ?? textBpm();
  knob.setAttribute("aria-disabled", String(bpm === undefined));
  if (bpm === undefined) return;
  knob.setAttribute("aria-valuenow", String(bpm));
  knob.classList.toggle("override", state.bpm !== null);
  el("tempoValue").textContent = `${Math.round(bpm)} BPM`;
  const angle = -135 + (270 * (Math.min(Math.max(bpm, TEMPO.min), TEMPO.max) - TEMPO.min)) / (TEMPO.max - TEMPO.min);
  el("tempoMark").style.setProperty("--angle", `${angle}deg`);
}

function setBpm(bpm) {
  if (textBpm() === undefined) return;
  state.bpm = bpm === null ? null : Math.min(Math.max(Math.round(bpm * 2) / 2, TEMPO.min), TEMPO.max);
  renderTempo();
  clearTimeout(state.tempoTimer);
  state.tempoTimer = setTimeout(() => state.playing && play(), 60);
}

function setupTempo() {
  const knob = el("tempo");
  let drag = null;
  knob.addEventListener("pointerdown", (event) => {
    if (textBpm() === undefined) return;
    drag = { y: event.clientY, bpm: state.bpm ?? textBpm() };
    knob.setPointerCapture(event.pointerId);
  });
  knob.addEventListener("pointermove", (event) => {
    if (drag) setBpm(drag.bpm + (drag.y - event.clientY) * 0.5);
  });
  knob.addEventListener("pointerup", () => (drag = null));
  knob.addEventListener("pointercancel", () => (drag = null));
  knob.addEventListener("wheel", (event) => {
    event.preventDefault();
    setBpm((state.bpm ?? textBpm()) + (event.deltaY < 0 ? 1 : -1) * (event.shiftKey ? 5 : 1));
  }, { passive: false });
  knob.addEventListener("keydown", (event) => {
    const step = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    event.stopPropagation();
    setBpm((state.bpm ?? textBpm()) + step * (event.shiftKey ? 5 : 1));
  });
  knob.addEventListener("dblclick", () => setBpm(null));
}

function highlightSlot(slot) {
  if (slot === state.slot) return;
  for (const cell of document.querySelectorAll(".now")) cell.classList.remove("now");
  state.slot = slot;
  drawScope();
  const perBar = state.score ? state.score.tempo.steps_per_bar : 16;
  el("lcdBar").textContent = slot === null ? "–" : Math.floor(slot / perBar) + 1;
  el("lcdStep").textContent = slot === null ? "––" : pad2((slot % perBar) + 1);
  if (slot === null) return;
  for (const cell of document.querySelectorAll(`[data-step="${slot}"]`)) cell.classList.add("now");
  const card = document.querySelector(`.card[data-bar="${Math.floor(slot / perBar)}"]`);
  if (card) card.classList.add("now");
  for (const [name, steps] of state.hits) {
    if (steps.has(slot) && !state.muted.has(name)) flash(name);
  }
}

function flash(name) {
  const pad = document.querySelector(`.pad[data-layer="${name}"]`);
  pad.classList.remove("hit");
  void pad.offsetWidth;
  pad.classList.add("hit");
}

function render() {
  const score = state.score;
  const slots = score.bars * score.tempo.steps_per_bar;
  state.hits = new Map(score.layers.map((layer) => [layer.name, new Set(layer.events.map((e) => e.step))]));
  state.amplitude = Array(slots).fill(0);
  for (const layer of score.layers) {
    for (const event of layer.events) {
      const length = Math.max(1, Math.min(Math.ceil(event.legato), slots - event.step));
      for (let offset = 0; offset < length; offset += 1) {
        state.amplitude[event.step + offset] += event.gain * score.mix[layer.name] * (offset ? 0.35 : 1);
      }
    }
  }
  el("stickerText").innerHTML = `${score.tempo.bpm}<br />BPM`;
  document.body.style.setProperty("--bpm", score.tempo.bpm);
  el("lcdSeed").textContent = `${score.bars} TAKTE · ${score.layers.reduce((n, l) => n + l.events.length, 0)} EVENTS`;
  renderPads();
  renderSong();
  renderRules();
  el("strudelCode").textContent =
    `${strudelCode() ?? ""}\n\n// Seed ${score.seed} · Sample-Seed ${score.sample_seed}\n` +
    score.samples.map((s) => `// ${s.s}  ←  ${s.id}`).join("\n");
  drawScope();
}

function renderPads() {
  const container = el("pads");
  container.textContent = "";
  state.score.layers.forEach((layer, index) => {
    const meta = LAYERS[layer.name];
    const pad = node("button", "pad");
    pad.dataset.layer = layer.name;
    pad.title = `${meta.label} stumm schalten (${index + 1})`;
    pad.classList.toggle("muted", state.muted.has(layer.name));
    pad.classList.toggle("empty", !layer.events.length);
    pad.append(node("span", "led"), node("span", "pad-key", meta.key), node("span", "pad-label", meta.label), node("span", "pad-count", layer.events.length));
    pad.addEventListener("click", () => toggleLayer(layer.name));
    container.appendChild(pad);
  });
}

function eventTitle(event) {
  const lines = [
    `Takt ${event.bar + 1}, Sechzehntel ${(event.step % 16) + 1}`,
    `${event.s}${event.note === null ? "" : ` · note ${event.note}`} · gain ${event.gain} · legato ${event.legato}`,
  ];
  for (const [key, value] of Object.entries(event.source)) {
    lines.push(`${key}: ${Array.isArray(value) ? value.map((v) => [].concat(v).join("→")).join(", ") : value}`);
  }
  return lines.join("\n");
}

function renderSong() {
  const score = state.score;
  const perBar = score.tempo.steps_per_bar;
  const slots = score.bars * perBar;
  const cells = new Map();
  const song = el("song");
  song.textContent = "";

  score.verses.forEach((verse, bar) => {
    const card = node("article", "card");
    card.dataset.bar = bar;
    const tab = node("div", "card-tab", `TAKT ${bar + 1} (${score.form === "sentence" ? "S" : "V"}.${pad2(bar + 1)})`);
    const words = verse.token_ids.map((id) => state.tokens.get(id).text).join(" ");
    const body = node("div", "card-body");
    body.appendChild(node("div", "card-verse", words));
    for (const layer of score.layers) {
      const meta = LAYERS[layer.name];
      const row = node("div", "lane");
      row.dataset.layer = layer.name;
      row.classList.toggle("muted", state.muted.has(layer.name));
      row.append(node("span", "lane-key", meta.key));
      const grid = node("div", "lane-grid");
      for (let i = 0; i < perBar; i += 1) {
        const step = bar * perBar + i;
        const cell = node("span", "cell" + (i % 4 === 0 ? " beat" : ""));
        cell.dataset.step = step;
        cells.set(`${layer.name}:${step}`, cell);
        grid.appendChild(cell);
      }
      row.appendChild(grid);
      body.appendChild(row);
    }
    card.append(tab, body);
    if (bar < score.verses.length - 1) card.appendChild(node("span", "arrow", "→"));
    song.appendChild(card);
  });

  for (const layer of score.layers) {
    for (const event of layer.events) {
      const length = Math.min(Math.ceil(event.legato), slots - event.step);
      for (let offset = 1; offset < length; offset += 1) cells.get(`${layer.name}:${event.step + offset}`).classList.add("hold");
    }
    for (const event of layer.events) {
      const cell = cells.get(`${layer.name}:${event.step}`);
      cell.classList.add("on");
      cell.title = cell.title ? `${cell.title}\n\n${eventTitle(event)}` : eventTitle(event);
    }
  }
}

function derivation() {
  const score = state.score;
  const rows = [];
  const row = (track, source, result) => rows.push({ track, source, result });
  const byName = Object.fromEntries(score.layers.map((layer) => [layer.name, layer]));
  const perBar = (events) => score.verses.map((verse) => events.filter((e) => e.bar === verse.bar));
  const profile = score.profile;
  row("Tempo", `Ø ${profile.tempo.sentence_words} Wörter pro Satz (normiert ${profile.tempo.norm})`, `${profile.tempo.bpm} BPM`);
  row(
    "Variation",
    `Verbanteil ${profile.variation.verb_share} (normiert ${profile.variation.norm})`,
    `Puls-Sample je Sechzehntel, fest pro Sample-Seed, Anteil ${profile.variation.norm} variiert: ${(byName.puls.variation?.positions ?? []).join(" ")}`,
  );
  perBar(byName.puls.events).forEach((events, bar) => {
    const source = events[0]?.source;
    if (!source) return;
    row(
      `Puls · Takt ${bar + 1}`,
      `${source.function_words} Funktionswörter in ${score.form === "sentence" ? "Satz" : "Vers"} ${source.unit}`,
      `Schläge auf ${source.positions.join(" ") || "–"}${source.filled.length ? ` · aufgefüllt ${source.filled.join(" ")}` : ""}`,
    );
  });
  for (const event of byName.bass.events) {
    row(
      `Bass · Takt ${event.bar + 1}`,
      `${event.source.text}: Satztiefe ${event.source.depth}`,
      `${event.s}, note ${event.note}, gehalten ${event.source.hold} Sechzehntel ` +
        `(${(event.source.hold / (score.tempo.cps * score.tempo.steps_per_bar)).toFixed(2)} s)`,
    );
  }
  const motifs = byName.motiv.source.motifs;
  perBar(byName.motiv.events).forEach((events, bar) => {
    const motif = motifs[bar];
    if (!motif) {
      row(`Motiv · Takt ${bar + 1}`, "keine im Text wiederholte Wortartenfolge im Vers", "schweigt");
      return;
    }
    const sequence = events.map((e) => e.source.pos).join(" → ");
    row(
      `Motiv · Takt ${bar + 1}`,
      `${motif.values.join(" ")} · ${motif.count}× im Text · „${motif.token_ids.map((id) => state.tokens.get(id).text).join(" ")}“` +
        (motif.standard ? " · Standardfolge (keine andere im Vers)" : ""),
      `${sequence} · notes ${events.map((e) => e.note).join(" ")}`,
    );
  });
  for (const event of byName.boegen.events) {
    row(
      `Bögen · ${event.source.from_verse} → ${event.source.to_verse}`,
      event.source.edges.map((edge) => edge.join(" → ")).join(", "),
      `note ${event.note}, ${event.legato} Sechzehntel über die Taktgrenze, gain ${event.gain}`,
    );
  }
  score.verses.forEach((verse) => {
    const echoed = score.layers.flatMap((layer) => layer.events).filter((e) => e.echo && e.bar === verse.bar);
    if (!echoed.length) return;
    const phrases = [...new Set(echoed.map((e) => e.source.echo.join(" ")))];
    row(
      `Echo · Takt ${verse.bar + 1}`,
      `wiederholt: ${phrases.map((phrase) => `„${phrase}“`).join(", ")}`,
      `${echoed.length} Noten mit ${Object.entries(echoed[0].echo).map(([k, v]) => `${k} ${v}`).join(", ")}`,
    );
  });
  const lemmas = new Map();
  for (const event of byName.leitwort.events) {
    if (!lemmas.has(event.source.lemma)) lemmas.set(event.source.lemma, []);
    lemmas.get(event.source.lemma).push(event);
  }
  for (const [lemma, events] of lemmas) {
    row("Leitwort", `Lemma „${lemma}“ ${events.length}×`, `${events[0].s}, note ${events[0].note}`);
  }
  if (!lemmas.size) row("Leitwörter", "kein Inhaltswort-Lemma wiederholt", "stumm");
  const effectText = {
    "accent bass": "Schlussakzent auf den Bass (+3 dB)",
    "no bass in bar": "kein Basston im Takt",
    "raise last motif note": "letzter Motivton eine Stufe höher",
    "no motif in bar": "kein Motivton im Takt",
    "bar +3 dB": "ganzer Takt +3 dB",
  };
  for (const mark of score.punctuation) {
    const effects = mark.effect
      .split("; ")
      .map((effect) => effectText[effect] || effect.replace(/^cut puls \((\d+) hits\) and motiv \((\d+) notes\) at the mark$/, "Puls und Motiv enden am Satzzeichen ($1 Schläge, $2 Motivtöne gekürzt)"));
    row(`Satzzeichen · Takt ${mark.bar + 1}`, `„${mark.text}“ bei Sechzehntel ${mark.step + 1}`, effects.join(", "));
  }
  for (const layer of score.layers) {
    const picked = score.samples.filter((s) => s.layer === layer.name);
    const length = (s) => (s.synth ? "Strudel-Synth" : `${s.duration.toFixed(2)} s`);
    row(
      `Samples · ${LAYERS[layer.name].label}`,
      `gezogen aus ${score.pools[layer.name]} getaggten Kandidaten`,
      picked.map((s) => `${s.s}: ${s.id} (${s.role}, ${length(s)})`).join(" · "),
    );
  }
  return rows;
}

function renderRules() {
  const list = el("soundRules");
  list.textContent = "";
  derivation().forEach(({ track, source, result }, index) => {
    const item = node("li");
    item.append(
      node("span", "rule-dot"),
      node("span", "rule-index", String(500 + index)),
      node("span", "rule-track", track),
      node("span", "rule-source", source),
      node("span", "rule-result", result),
    );
    list.appendChild(item);
  });
}

function drawScope() {
  const canvas = el("scope");
  const context = canvas.getContext("2d");
  const { width, height } = canvas;
  context.clearRect(0, 0, width, height);
  const amplitude = state.amplitude;
  if (!amplitude.length) return;
  const peak = Math.max(...amplitude, 0.001);
  const column = width / amplitude.length;
  const middle = height / 2;
  context.strokeStyle = "rgba(79, 179, 169, 0.35)";
  context.beginPath();
  context.moveTo(0, middle);
  context.lineTo(width, middle);
  context.stroke();
  amplitude.forEach((value, index) => {
    const reach = (value / peak) * (middle - 8);
    context.fillStyle = index === state.slot ? "#ec5a29" : "#4fb3a9";
    const x = index * column + column * 0.2;
    context.fillRect(x, middle - reach, Math.max(1, column * 0.6), reach * 2 || 1);
  });
  if (state.slot !== null) {
    context.fillStyle = "#ec5a29";
    context.fillRect(state.slot * column + column / 2 - 1, 4, 2, height - 8);
  }
}

function typing(event) {
  return event.target.matches("textarea, input, select");
}

document.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
    event.preventDefault();
    analyze();
    return;
  }
  if (typing(event) || event.metaKey || event.ctrlKey || event.altKey || !state.score) return;
  if (event.code === "Space") {
    event.preventDefault();
    togglePlay();
    return;
  }
  const layer = state.score.layers[parseInt(event.key, 10) - 1];
  if (layer) toggleLayer(layer.name);
});

el("analyze").addEventListener("click", analyze);
el("play").addEventListener("click", play);
el("stop").addEventListener("click", stop);
el("reroll").addEventListener("click", () => {
  state.sampleSeed = Math.random().toString(16).slice(2, 10);
  refreshSound();
});
el("sampleSeed").addEventListener("change", () => {
  state.sampleSeed = el("sampleSeed").value.trim() || null;
  refreshSound();
});
el("screenMode").addEventListener("click", () => {
  const settings = el("screenSettings").hidden;
  el("screenSettings").hidden = !settings;
  el("scope").hidden = settings;
  el("screenMode").setAttribute("aria-pressed", String(settings));
  el("screenTab").textContent = settings ? "SETUP" : "SOUND";
});

el("text").value = localStorage.getItem(TEXT_KEY) ?? DEFAULT_TEXT;
setupTempo();
startStrudel();
analyze();
