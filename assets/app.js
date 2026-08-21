(() => {
  "use strict";
  const state = { revealed: [], sort: ["date", -1] };
  const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
  const dateFmt = new Intl.DateTimeFormat("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
  const $ = (id) => document.getElementById(id);
  function pct(value) {
    if (value === null || value === undefined) return "—";
    return (value >= 0 ? "+" : "") + (value * 100).toFixed(1) + "%";
  }
  function dateText(value) { return value ? dateFmt.format(new Date(value)) : "—"; }
  function horizon(performance, name) { return performance?.horizons?.[name] || {}; }
  function latency(entry) {
    const hours = (new Date(entry.sealed_at) - new Date(entry.record.generated_at)) / 36e5;
    return hours < 48 ? Math.max(0, hours).toFixed(1) + "h" : (hours / 24).toFixed(1) + "d";
  }
  function badge(text, kind) {
    const span = document.createElement("span");
    span.className = "badge badge-" + kind;
    span.textContent = text;
    return span;
  }
  function verdictCell(result) {
    const wrapper = document.createElement("div");
    wrapper.className = "verdict";
    if (result.excess_return === undefined || result.excess_return === null) {
      wrapper.append(badge(result.verdict === "data_gap" ? "DATA GAP" : "PENDING", "pending"));
      return wrapper;
    }
    wrapper.append(badge(pct(result.excess_return), result.verdict));
    const small = document.createElement("small");
    small.textContent = result.verdict;
    wrapper.append(small);
    return wrapper;
  }
  function rowView(item) {
    const entry = item.entry;
    const performance = item.performance;
    const record = entry.record;
    const row = document.createElement("tr");
    if (record.voided) {
      row.className = "voided";
      row.title = "Voided: " + record.voided.reason;
    }
    const values = [
      dateText(record.generated_at),
      record.ticker,
      record.rating.replaceAll("_", " "),
      record.conviction,
      record.provenance === "backfilled" ? "BACKFILLED" : "LIVE",
      performance?.entry_price == null ? "—" : money.format(performance.entry_price),
      money.format(record.target_price),
    ];
    values.forEach((value, index) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      if (index === 1) cell.className = "ticker";
      if (index === 4) cell.className = "provenance";
      if (index === 2) {
        cell.textContent = "";
        const kind = record.rating.includes("BUY") ? "buy" : record.rating.includes("SELL") ? "sell" : "hold";
        cell.append(badge(value, kind));
      }
      row.append(cell);
    });
    for (const name of ["6m", "12m"]) {
      const cell = document.createElement("td");
      cell.append(verdictCell(horizon(performance, name)));
      row.append(cell);
    }
    const outcome = document.createElement("td");
    outcome.textContent = (performance?.target_stop?.outcome || "not_evaluable").replaceAll("_", " ");
    row.append(outcome);
    const seal = document.createElement("td");
    seal.textContent = latency(entry);
    row.append(seal);
    return row;
  }
  function sortValue(item, key) {
    const r = item.entry.record;
    const p = item.performance || {};
    const map = {
      date: r.generated_at,
      ticker: r.ticker,
      rating: r.rating,
      conviction: r.conviction,
      provenance: r.provenance,
      entry: p.entry_price,
      target: r.target_price,
      six: horizon(p, "6m").excess_return,
      twelve: horizon(p, "12m").excess_return,
      outcome: p.target_stop?.outcome,
      latency: new Date(item.entry.sealed_at) - new Date(r.generated_at),
    };
    return map[key] ?? -Infinity;
  }
  function renderTable() {
    const table = $("calls-table");
    const body = table.querySelector("tbody");
    body.textContent = "";
    const key = state.sort[0];
    const direction = state.sort[1];
    const rows = [...state.revealed].sort((a, b) => {
      const av = sortValue(a, key);
      const bv = sortValue(b, key);
      return (typeof av === "string" ? av.localeCompare(bv) : av - bv) * direction;
    });
    rows.forEach((item) => body.append(rowView(item)));
    $("calls-empty").hidden = rows.length > 0;
  }
  function wireSort(tableId) {
    document.querySelectorAll("#" + tableId + " th").forEach((th) => th.addEventListener("click", () => {
      const key = th.dataset.sort;
      state.sort = state.sort[0] === key ? [key, state.sort[1] * -1] : [key, 1];
      document.querySelectorAll("#" + tableId + " th").forEach((node) => node.removeAttribute("aria-sort"));
      th.setAttribute("aria-sort", state.sort[1] === 1 ? "ascending" : "descending");
      renderTable();
    }));
  }
  function summary(performance, calls) {
    const aggregate = performance.aggregates || {};
    $("stat-revealed").textContent = aggregate.revealed ?? calls.filter((item) => item.state === "revealed").length;
    for (const name of ["6m", "12m"]) {
      const item = aggregate.horizons?.[name] || {};
      $("stat-hit-" + name).textContent = item.hit_rate == null ? "—" : Math.round(item.hit_rate * 100) + "%";
      $("stat-n-" + name).textContent = item.n ? item.n + " resolved call" + (item.n === 1 ? "" : "s") : "No resolved calls";
      if (name === "12m") $("stat-median-12m").textContent = pct(item.median_excess_return);
    }
    const sealed = aggregate.sealed ?? calls.filter((item) => item.state === "sealed").length;
    const pending = (aggregate.horizons?.["6m"]?.pending || 0) + (aggregate.horizons?.["12m"]?.pending || 0);
    $("stat-pending").textContent = pending;
    $("stat-sealed").textContent = sealed;
    $("sealed-count").textContent = sealed + " call" + (sealed === 1 ? "" : "s") + " sealed, awaiting reveal";
    $("updated-at").textContent = performance.computed_at ? "Prices refreshed " + dateText(performance.computed_at) : "Awaiting first price refresh";
  }
  function drawScatter(items) {
    const canvas = $("scatter");
    const ctx = canvas.getContext("2d");
    const scale = window.devicePixelRatio || 1;
    const width = canvas.clientWidth || 800;
    const height = 240;
    canvas.width = width * scale;
    canvas.height = height * scale;
    ctx.scale(scale, scale);
    ctx.clearRect(0, 0, width, height);
    const pad = 44;
    const axis = width / 2;
    ctx.strokeStyle = "rgba(255,255,255,.2)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(axis, 20);
    ctx.lineTo(axis, height - 26);
    ctx.stroke();
    ctx.fillStyle = "rgba(255,255,255,.48)";
    ctx.font = "11px system-ui";
    ctx.fillText("6 months", 8, 78);
    ctx.fillText("12 months", 8, 170);
    ctx.fillText("SPY", axis + 6, height - 9);
    const points = [];
    items.forEach((item) => ["6m", "12m"].forEach((name, index) => {
      const value = horizon(item.performance, name).excess_return;
      if (value != null) points.push({ value, y: index ? 164 : 72, correct: horizon(item.performance, name).verdict === "correct" });
    }));
    const max = Math.max(.1, ...points.map((point) => Math.abs(point.value)));
    points.forEach((point) => {
      const x = axis + point.value / max * (width / 2 - pad);
      ctx.beginPath();
      ctx.arc(x, point.y, 5, 0, Math.PI * 2);
      ctx.fillStyle = point.correct ? "#d6ef88" : "#df705f";
      ctx.fill();
    });
    ctx.strokeStyle = "rgba(255,255,255,.12)";
    for (const y of [72, 164]) {
      ctx.beginPath();
      ctx.moveTo(pad, y);
      ctx.lineTo(width - pad, y);
      ctx.stroke();
    }
  }
  async function init() {
    try {
      const responses = await Promise.all([
        fetch("data/calls.json", { cache: "no-store" }),
        fetch("data/performance.json", { cache: "no-store" }),
      ]);
      if (!responses[0].ok || !responses[1].ok) throw new Error("Public data is unavailable");
      const callsPayload = await responses[0].json();
      const performance = await responses[1].json();
      const revealed = callsPayload.calls
        .filter((entry) => entry.state === "revealed")
        .map((entry) => ({ entry, performance: performance.calls?.[entry.call_id] }));
      state.revealed = revealed;
      const live = revealed.filter((item) => item.entry.record.provenance === "live");
      summary(performance, callsPayload.calls);
      renderTable();
      drawScatter(live);
      window.addEventListener("resize", () => drawScatter(live), { passive: true });
    } catch (error) {
      $("updated-at").textContent = "Data refresh unavailable";
      console.error(error);
    }
  }
  wireSort("calls-table");
  init();
})();
