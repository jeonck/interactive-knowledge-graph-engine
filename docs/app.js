/* Graph Engine — D3 front-end over the Python engine's JSON output. */
const LABEL = {
  pagerank: "PageRank", authority: "Authority (HITS)", hub: "Hub (HITS)",
  betweenness: "Betweenness", closeness: "Closeness",
  degree: "Degree", in_degree: "In-degree", out_degree: "Out-degree",
};
const EXPLAIN = {
  pagerank: "influence, weighting each link by how important its source is",
  authority: "cited by many good hubs — an original source",
  hub: "points at many good authorities — an overview or index",
  betweenness: "sits on the shortest paths between other nodes — a bridge",
  closeness: "close to everything else in the network",
  degree: "raw number of connections",
  in_degree: "how many nodes point here",
  out_degree: "how many nodes it points at",
};
const COLORS = d3.schemeTableau10.concat(d3.schemeSet3);
const fmt = d3.format(".4f");
const fmtP = p => (p == null ? "–" : p < 1e-4 ? p.toExponential(1) : d3.format(".4f")(p));

const el = id => document.getElementById(id);
const S = { data: null, metric: "pagerank", sigOnly: false, selected: null,
            hidden: new Set(), userZoomed: false };

// The toolbar wraps at narrow widths, so the graph pane measures the chrome
// above it instead of trusting a hard-coded offset.
function measureChrome() {
  const h = document.querySelector("header").offsetHeight + document.querySelector(".toolbar").offsetHeight;
  document.documentElement.style.setProperty("--chrome", h + "px");
}
measureChrome();

const svg = d3.select("#graph");
const root = svg.append("g");
const gLinks = root.append("g").attr("class", "links");
const gNodes = root.append("g").attr("class", "nodes");
const gLabels = root.append("g").attr("class", "labels");
const zoom = d3.zoom().scaleExtent([0.15, 8]).on("zoom", e => {
  root.attr("transform", e.transform);
  if (e.sourceEvent) S.userZoomed = true;  // stop auto-fitting once they take over
});
svg.call(zoom).on("dblclick.zoom", null);

let sim = null;

/* ---------- data ---------- */
init();
async function init() {
  const index = await (await fetch("data/index.json")).json();
  const sel = el("dataset");
  sel.innerHTML = index.map(d => `<option value="${d.file}">${d.name} — ${d.nodes} nodes</option>`).join("");
  sel.onchange = () => load(sel.value);
  el("metric").onchange = e => { S.metric = e.target.value; draw(); };
  el("sigonly").onchange = e => { S.sigOnly = e.target.checked; draw(); };
  el("search").oninput = e => search(e.target.value);
  el("reset").onclick = () => {
    S.hidden.clear(); S.selected = null; S.userZoomed = false;
    el("sigonly").checked = S.sigOnly = false;
    detail(null); draw(); fit(true);
  };
  await load(index[0].file);
}

async function load(file) {
  el("loading").hidden = false;
  const data = await (await fetch("data/" + file)).json();
  data.file = file;
  data.byId = new Map(data.nodes.map(n => [n.id, n]));
  data.clusterName = {};
  for (const n of data.nodes) {
    const best = data.clusterName[n.community];
    if (!best || n.scores.pagerank.value > best.scores.pagerank.value) data.clusterName[n.community] = n;
  }
  S.data = data; S.selected = null; S.userZoomed = false; S.hidden.clear();
  el("metric").innerHTML = data.metrics.map(m => `<option value="${m}">${LABEL[m] || m}</option>`).join("");
  if (!data.metrics.includes(S.metric)) S.metric = data.metrics[0];
  el("metric").value = S.metric;
  build();
  ticks = 0;
  summary(); findings(); draw();
  el("loading").hidden = true;
}

/* ---------- graph ---------- */
function build() {
  const d = S.data;
  const nodes = d.nodes.map(n => Object.assign({}, n));
  const byId = new Map(nodes.map(n => [n.id, n]));
  const links = d.links.map(l => ({ source: byId.get(l.source), target: byId.get(l.target), weight: l.weight }));
  d.sim = { nodes, links, byId };

  svg.select("defs").remove();
  svg.append("defs").append("marker")
    .attr("id", "arrow").attr("viewBox", "0 -5 10 10").attr("refX", 16)
    .attr("markerWidth", 5).attr("markerHeight", 5).attr("orient", "auto")
    .append("path").attr("d", "M0,-4L9,0L0,4").attr("fill", "#3a4667");

  // A 250-node graph with 6k edges needs a looser hand than a 30-node one.
  const dense = links.length > 1500;
  const comms = [...new Set(nodes.map(n => n.community))].sort((a, b) => a - b);
  d.dense = dense;
  const w = el("canvas").clientWidth, h = el("canvas").clientHeight;
  const R = Math.min(w, h) * (comms.length > 1 ? 0.5 : 0);
  const spot = new Map(comms.map((c, i) => {
    const a = (2 * Math.PI * i) / comms.length - Math.PI / 2;
    return [c, [w / 2 + R * Math.cos(a), h / 2 + R * Math.sin(a)]];
  }));
  const anchor = n => spot.get(n.community);
  if (sim) sim.stop();
  sim = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(links).id(n => n.id)
      .distance(l => (dense ? 70 : 40 + 30 / (1 + l.weight))).strength(dense ? 0.03 : 0.35))
    .force("charge", d3.forceManyBody().strength(dense ? -260 : -260))
    .force("center", d3.forceCenter(w / 2, h / 2))
    .force("collide", d3.forceCollide(n => radius(n) + 3))
    // Pull each community toward its own anchor: without it a dense graph is
    // one grey ball and the cluster colours say nothing about position.
    .force("x", d3.forceX(n => anchor(n)[0]).strength(dense ? 0.45 : 0.05))
    .force("y", d3.forceY(n => anchor(n)[1]).strength(dense ? 0.45 : 0.05))
    .on("tick", tick)
    .on("end", () => fit());

  const link = gLinks.selectAll("line").data(links).join("line")
    .attr("stroke", "#2b3452").attr("stroke-width", dense ? 0.6 : 1)
    .attr("marker-end", d.globals.directed && !dense ? "url(#arrow)" : null);

  const node = gNodes.selectAll("circle").data(nodes, n => n.id).join("circle")
    .attr("stroke", "#0b1020").attr("stroke-width", 1.2)
    .on("click", (e, n) => select(n.id))
    .on("mouseenter", (e, n) => hover(n, e))
    .on("mousemove", (e) => moveTip(e))
    .on("mouseleave", () => { el("tip").hidden = true; draw(); })
    .call(d3.drag()
      .on("start", (e, n) => {
        S.userZoomed = true;  // hands on the graph: stop re-framing under them
        if (!e.active) sim.alphaTarget(0.25).restart();
        n.fx = n.x; n.fy = n.y;
      })
      .on("drag", (e, n) => { n.fx = e.x; n.fy = e.y; })
      .on("end", (e, n) => { if (!e.active) sim.alphaTarget(0); n.fx = n.fy = null; }));

  gLabels.selectAll("text").data(nodes, n => n.id).join("text")
    .text(n => n.label).attr("font-size", 10).attr("fill", "#c8d3ea")
    .attr("text-anchor", "middle").attr("pointer-events", "none")
    .attr("paint-order", "stroke").attr("stroke", "#0b1020").attr("stroke-width", 3);

  d.neighbors = new Map(nodes.map(n => [n.id, new Set()]));
  for (const l of links) { d.neighbors.get(l.source.id).add(l.target.id); d.neighbors.get(l.target.id).add(l.source.id); }
  d.view = { link, node };
}

let ticks = 0;
function tick() {
  const { link, node } = S.data.view;
  if (++ticks % 25 === 0) fit(false, true);  // keep the layout framed while it settles
  link.attr("x1", l => l.source.x).attr("y1", l => l.source.y)
      .attr("x2", l => l.target.x).attr("y2", l => l.target.y);
  node.attr("cx", n => n.x).attr("cy", n => n.y);
  gLabels.selectAll("text").attr("x", n => n.x).attr("y", n => n.y - radius(n) - 4);
}

const score = n => n.scores[S.metric] || { value: 0 };
function radius(n) {
  const max = S.data.max?.[S.metric] ?? 1;
  return 4 + 20 * Math.sqrt(score(n).value / (max || 1));
}
function visible(n) {
  if (S.hidden.has(n.community)) return false;
  if (S.sigOnly && !score(n).sig) return false;
  return true;
}

function draw() {
  const d = S.data;
  d.max = {};
  for (const m of d.metrics) d.max[m] = d3.max(d.nodes, n => n.scores[m].value);
  const { link, node } = d.view;
  const sel = S.selected, near = sel ? d.neighbors.get(sel) : null;

  node.attr("r", radius)
    .attr("fill", n => COLORS[n.community % COLORS.length])
    .attr("opacity", n => !visible(n) ? 0.07 : sel ? (n.id === sel || near.has(n.id) ? 1 : 0.18) : 0.95)
    .attr("stroke", n => (score(n).sig ? "#e6ebf7" : "#0b1020"))
    .attr("stroke-width", n => (score(n).sig ? 1.6 : 1.2));

  link.attr("stroke", l => sel && (l.source.id === sel || l.target.id === sel) ? "#5eead4" : "#2b3452")
      .attr("stroke-opacity", l => {
        if (!visible(l.source) || !visible(l.target)) return 0.02;
        if (!sel) return d.dense ? 0.09 : 0.5;
        return (l.source.id === sel || l.target.id === sel) ? 0.9 : 0.04;
      })
      .attr("stroke-width", l => (sel && (l.source.id === sel || l.target.id === sel) ? 1.8 : 1));

  const cutoff = d3.quantile(d.nodes.filter(visible).map(n => n.scores[S.metric].value).sort(d3.ascending), d.dense ? 0.94 : 0.9) ?? 0;
  gLabels.selectAll("text").attr("display", n => {
    if (!visible(n)) return "none";
    if (sel) return (n.id === sel || near.has(n.id)) ? null : "none";
    return score(n).value >= cutoff ? null : "none";
  }).attr("font-weight", n => (n.id === sel ? 700 : 400));

  sim.force("collide").radius(n => radius(n) + 3);
  sim.alpha(0.25).restart();
  ranking(); legend();
  el("rank-metric").textContent = "· " + (LABEL[S.metric] || S.metric);
}

function fit(force, instant) {
  if (S.userZoomed && !force) return;
  const w = el("canvas").clientWidth, h = el("canvas").clientHeight;
  const ns = S.data.sim.nodes.filter(n => isFinite(n.x));
  if (!ns.length) return;
  const [x0, x1] = d3.extent(ns, n => n.x), [y0, y1] = d3.extent(ns, n => n.y);
  const k = Math.max(0.15, Math.min(1.6, 0.92 * Math.min(w / (x1 - x0 + 80), h / (y1 - y0 + 80))));
  const t = d3.zoomIdentity.translate(w / 2, h / 2).scale(k)
    .translate(-(x0 + x1) / 2, -(y0 + y1) / 2);
  (instant ? svg : svg.transition().duration(450)).call(zoom.transform, t);
}

/* ---------- panels ---------- */
function summary() {
  const g = S.data.globals, d = S.data;
  const modVerdict = g.modularity_z > 3
    ? `clustering is real (z = ${g.modularity_z.toFixed(1)} vs. random)`
    : `clustering is no stronger than chance (z = ${g.modularity_z.toFixed(1)})`;
  el("summary").innerHTML = `
    <h2>${d.name}</h2>
    <p class="muted" style="margin:-4px 0 12px;font-size:13px">${d.description}</p>
    <div class="stats">
      <div class="stat"><b>${g.nodes}</b><span>nodes</span></div>
      <div class="stat"><b>${g.edges}</b><span>${g.directed ? "directed " : ""}edges</span></div>
      <div class="stat"><b>${g.communities}</b><span>communities</span></div>
      <div class="stat"><b>${g.modularity}</b><span>modularity</span></div>
      <div class="stat"><b>${g.rewires}</b><span>null rewirings</span></div>
      <div class="stat"><b>${(g.density * 100).toFixed(2)}%</b><span>density</span></div>
    </div>
    <p class="src">${modVerdict}. Random graphs with identical degrees average ${g.modularity_null_mean}.
    ${d.source ? "Source: " + d.source : ""}
    · <a href="data/${d.file}" download>download JSON</a></p>`;
}

function topBy(metric) {
  return S.data.nodes.filter(n => n.scores[metric])
    .sort((a, b) => b.scores[metric].value - a.scores[metric].value);
}

function findings() {
  const d = S.data, g = d.globals;
  const has = m => d.metrics.includes(m);
  const link = n => `<em onclick="window.__pick('${n.id.replace(/'/g, "\\'")}')">${n.label}</em>`;
  const zed = (n, m) => `z = ${n.scores[m].z > 0 ? "+" : ""}${n.scores[m].z.toFixed(1)}, p ${n.scores[m].p < 1e-4 ? "&lt; 1e-4" : "= " + fmtP(n.scores[m].p)}`;
  // Never dress up a score that did not clear the null model.
  const verdict = (n, m, real, notreal) => n.scores[m].sig
    ? `${real} (${zed(n, m)})` : `${notreal} — ${zed(n, m)}, no more than its own degree predicts`;
  const items = [];

  const pr = topBy("pagerank");
  if (pr.length) items.push(`<span class="q">What is the core concept?</span>
    ${link(pr[0])} tops PageRank, ${verdict(pr[0], "pagerank",
      "further above its degree-matched twins than chance allows",
      "but the ranking is unremarkable")}.
    ${pr[1] ? "Next: " + link(pr[1]) + "." : ""}`);

  if (has("hub") && has("authority")) {
    const hub = topBy("hub")[0], auth = topBy("authority")[0];
    items.push(`<span class="q">Which nodes collect, which are cited?</span>
      Best hub ${link(hub)}${hub.scores.hub.sig ? " (significant)" : ""} points at the important
      material — an overview. Best authority ${link(auth)}${auth.scores.authority.sig ? " (significant)" : ""}
      is what the good hubs keep pointing back to — a source.`);
  }

  const br = topBy("betweenness")[0];
  if (br) {
    const spans = new Set([...d.neighbors.get(br.id)].map(id => d.byId.get(id).community));
    const sigs = topBy("betweenness").filter(n => n.scores.betweenness.sig).length;
    items.push(`<span class="q">What bridges separate domains?</span>
      ${link(br)} ${verdict(br, "betweenness",
        "sits on more shortest paths than random rewiring produces",
        "carries the most shortest paths")}, touching ${spans.size} of the ${g.communities} communities.
      ${sigs ? sigs + " node" + (sigs > 1 ? "s" : "") + " clear the 5% FDR bar on betweenness." : "No node clears the 5% FDR bar here."}`);
  }

  const clusters = Object.entries(d.clusterName)
    .sort((a, b) => b[1].scores.pagerank.value - a[1].scores.pagerank.value).slice(0, 4)
    .map(([c, n]) => `<span style="color:${COLORS[c % COLORS.length]}">■</span> ${link(n)}`);
  items.push(`<span class="q">How does the knowledge split into topics?</span>
    ${g.communities} communities, modularity ${g.modularity}
    ${g.modularity_z > 3 ? `— far denser inside than any degree-matched random graph (z = +${g.modularity_z.toFixed(1)})`
      : `— but random graphs with the same degrees reach ${g.modularity_null_mean} on their own (z = ${g.modularity_z > 0 ? "+" : ""}${g.modularity_z.toFixed(1)}), so treat the split as tentative`}.
    Largest, by their central node: ${clusters.join(", ")}.`);

  el("findings").innerHTML = `<h2>Findings</h2><ul>${items.map(i => `<li>${i}</li>`).join("")}</ul>`;
}

function ranking() {
  const rows = S.data.nodes
    .filter(n => !S.hidden.has(n.community) && (!S.sigOnly || n.scores[S.metric].sig))
    .sort((a, b) => b.scores[S.metric].value - a.scores[S.metric].value).slice(0, 15);
  const body = rows.map((n, i) => {
    const s = n.scores[S.metric];
    return `<tr data-id="${encodeURIComponent(n.id)}" class="${n.id === S.selected ? "on" : ""}">
      <td class="rank">${i + 1}</td>
      <td><span class="dot" style="background:${COLORS[n.community % COLORS.length]}"></span>${n.label}
        ${s.z == null ? "" : `<span class="badge ${s.sig ? "sig" : "ns"}">${s.sig ? "sig" : "n.s."}</span>`}</td>
      <td class="n">${fmt(s.value)}</td>
      <td class="n">${s.z == null ? "" : (s.z > 0 ? "+" : "") + s.z.toFixed(1)}</td></tr>`;
  }).join("");
  const table = el("ranking");
  table.querySelector("tbody").innerHTML = body || `<tr><td class="muted">No node passes the significance filter for this metric.</td></tr>`;
  table.querySelectorAll("tr[data-id]").forEach(tr => tr.onclick = () => select(decodeURIComponent(tr.dataset.id)));
}

function legend() {
  const d = S.data;
  const counts = d3.rollup(d.nodes, v => v.length, n => n.community);
  el("legend").innerHTML = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10)
    .map(([c, k]) => `<span class="${S.hidden.has(c) ? "off" : ""}" data-c="${c}">
      <i style="background:${COLORS[c % COLORS.length]}"></i>${d.clusterName[c].label} (${k})</span>`).join("");
  el("legend").querySelectorAll("span").forEach(s => s.onclick = () => {
    const c = +s.dataset.c;
    S.hidden.has(c) ? S.hidden.delete(c) : S.hidden.add(c);
    draw();
  });
}

function detail(id) {
  const box = el("detail");
  if (!id) { box.innerHTML = `<h2>Node</h2><p class="muted">Click a node to inspect every metric and its null-model comparison.</p>`; return; }
  const n = S.data.byId.get(id), d = S.data;
  const deg = d.neighbors.get(id).size;
  const rows = d.metrics.map(m => {
    const s = n.scores[m];
    return `<tr><td>${LABEL[m] || m}</td><td class="n">${fmt(s.value)}</td>
      <td class="n">${s.z == null ? "–" : (s.z > 0 ? "+" : "") + s.z.toFixed(1)}</td>
      <td class="n">${s.z == null ? "–" : fmtP(s.p)}</td>
      <td>${s.z == null ? "" : `<span class="badge ${s.sig ? "sig" : "ns"}">${s.sig ? "sig" : "n.s."}</span>`}</td></tr>`;
  }).join("");
  const wins = d.metrics.filter(m => n.scores[m].sig).map(m => LABEL[m]);
  box.innerHTML = `<h2>Node</h2>
    <h3><span class="dot" style="background:${COLORS[n.community % COLORS.length]}"></span>${n.label}</h3>
    <p class="sub">${deg} connections · cluster “${d.clusterName[n.community].label}” ·
      ${wins.length ? "beats the null model on " + wins.join(", ") : "nothing here beats its own degree"}</p>
    <table><tbody>
      <tr><td class="muted">metric</td><td class="n muted">score</td><td class="n muted">z</td><td class="n muted">p</td><td></td></tr>
      ${rows}</tbody></table>
    <p class="src">${EXPLAIN[S.metric] ? "Current ranking: " + EXPLAIN[S.metric] + "." : ""}</p>`;
}

/* ---------- interaction ---------- */
function select(id) {
  S.selected = id && S.selected === id ? null : id;
  detail(S.selected); draw();
  if (S.selected) {
    const n = S.data.sim.byId.get(S.selected);
    const w = el("canvas").clientWidth, h = el("canvas").clientHeight;
    svg.transition().duration(500).call(zoom.transform,
      d3.zoomIdentity.translate(w / 2, h / 2).scale(1.4).translate(-n.x, -n.y));
  }
}
window.__pick = select;

function hover(n, e) {
  const s = n.scores[S.metric];
  el("tip").innerHTML = `<b>${n.label}</b>
    ${LABEL[S.metric]}: ${fmt(s.value)}${s.z == null ? "" : ` · z ${s.z > 0 ? "+" : ""}${s.z.toFixed(1)} · p ${fmtP(s.p)}`}<br>
    ${s.z == null ? "" : `random twin averages ${fmt(s.null_mean)}`}
    <br><span style="color:#93a0bf">${S.data.neighbors.get(n.id).size} connections · cluster ${S.data.clusterName[n.community].label}</span>`;
  el("tip").hidden = false; moveTip(e);
  const near = S.data.neighbors.get(n.id);
  S.data.view.node.attr("opacity", m => !visible(m) ? 0.07 : (m.id === n.id || near.has(m.id) ? 1 : 0.2));
  S.data.view.link.attr("stroke-opacity", l => (l.source.id === n.id || l.target.id === n.id) ? 0.9 : 0.06);
}
function moveTip(e) {
  const r = el("canvas").getBoundingClientRect(), t = el("tip");
  t.style.left = Math.min(e.clientX - r.left + 14, r.width - 275) + "px";
  t.style.top = (e.clientY - r.top + 14) + "px";
}

function search(q) {
  q = q.trim().toLowerCase();
  if (!q) return;
  const hit = S.data.nodes.find(n => n.label.toLowerCase().startsWith(q))
          || S.data.nodes.find(n => n.label.toLowerCase().includes(q));
  if (hit && hit.id !== S.selected) select(hit.id);
}

let resizeTimer;
addEventListener("resize", () => {
  if (!S.data) return;
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    measureChrome();
    sim.force("center", d3.forceCenter(el("canvas").clientWidth / 2, el("canvas").clientHeight / 2))
       .alpha(0.3).restart();
  }, 200);
});
