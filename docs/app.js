// Flames of Orion quick-play sheet generator. Standalone, no backend.
// Data comes from data.js (scripts/export_web_data.py); this is a port of the Python
// generator that is free to drift from it - the same seed need not give the same mechs.
(() => {
  "use strict";
  const D = window.FOO_DATA;

  // ---- seeded RNG (mulberry32 over a string hash) ------------------------
  function hashSeed(str) {
    let h = 1779033703 ^ str.length;
    for (let i = 0; i < str.length; i++) {
      h = Math.imul(h ^ str.charCodeAt(i), 3432918353);
      h = (h << 13) | (h >>> 19);
    }
    return (h ^ (h >>> 16)) >>> 0;
  }
  function makeRng(seed) {
    let a = hashSeed(String(seed));
    const random = () => {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    const die = (n) => 1 + Math.floor(random() * n);
    return { random, die, int: (lo, hi) => lo + Math.floor(random() * (hi - lo + 1)) };
  }

  // ---- footnote bookkeeping ----------------------------------------------
  const EFFECT_STAT = {
    set_armor: "AR", speed_delta: "S", cs_delta: "CS", heat_limit_delta: "HL",
    hull_points_delta: "HP", platform_slots_delta: "PF",
  };
  const CONDITIONAL_STAT = {
    cs_delta_vs_hot_target: "CS", cs_delta_melee: "CS", cs_delta_ranged: "CS",
  };
  const MARK = { S: "*", CS: "†", AR: "‡", HL: "§", HP: "¶", PF: "#" };
  const statsOf = (map, effect) =>
    Object.entries(map).filter(([k]) => k in (effect || {})).map(([, v]) => v);

  function applied(text, effect) {
    const tags = statsOf(EFFECT_STAT, effect).map((s) => `already in ${s}${MARK[s]}`)
      .concat(statsOf(CONDITIONAL_STAT, effect).map((s) => `can modify ${s}${MARK[s]}, not included`));
    if (!tags.length) return text;
    const tag = `(${tags.join("; ")})`;
    return text ? `${text} ${tag}` : tag;
  }

  // ---- generation --------------------------------------------------------
  function generateMech(frameKey, rng, opts) {
    const f = D.frames[frameKey];
    const u = {
      frame: frameKey, speed: f.speed, cs: f.combat_skill, ar: f.armor, hp: f.hull_points,
      hl: f.heat_limit, pf: f.platform_slots, weapons: [], upgrades: [], perk: null,
    };
    let slots = f.platform_slots;
    for (let guard = 0; slots > 0 && guard < 80; guard++) {
      if (rng.die(6) <= 4) {
        const kind = rng.die(6) <= 3 ? "ranged" : "melee";
        const w = D[kind][rng.die(8) - 1];
        if (w.slots > slots) continue;
        slots -= w.slots;
        u.weapons.push({ kind, w, ammo: null });
      } else {
        const up = D.upgrades[rng.int(0, D.upgrades.length - 1)];
        if (!up.stackable && u.upgrades.includes(up)) continue;
        u.upgrades.push(up);
        slots -= 1;
        if (up.effect.free_slot) slots += 1;
      }
    }
    if (opts.ammo) {
      for (const wi of u.weapons) {
        if (wi.kind !== "ranged" || wi.w.noAmmo) continue;
        if (rng.random() < 0.4) wi.ammo = D.ammo[rng.int(0, D.ammo.length - 1)];
      }
    }
    for (const up of u.upgrades) {
      const e = up.effect;
      if ("set_armor" in e) u.ar = e.set_armor;
      u.speed += e.speed_delta || 0;
      u.cs += e.cs_delta || 0;
      u.hl += e.heat_limit_delta || 0;
      u.pf += e.platform_slots_delta || 0;
      u.hp += e.hull_points_delta || 0;
    }
    const a = D.callSignA, b = D.callSignB;
    u.name = `${a[rng.int(0, 5)][rng.int(0, 5)]} ${b[rng.int(0, 5)][rng.int(0, 5)]}`;
    return u;
  }

  function pickPerk(u, rng) {
    const kinds = new Set(u.weapons.map((w) => w.kind));
    // never a melee bonus on a mech with no melee weapon, or ranged on a mech with no ranged
    const ok = D.perks.filter((p) => !p.requires || kinds.has(p.requires));
    const perk = ok[rng.int(0, ok.length - 1)];
    const e = perk.effect || {};
    u.speed += e.speed_delta || 0;
    u.hl += e.heat_limit_delta || 0;
    u.perk = perk;
  }

  function totalCost(u) {
    let t = D.mechCost;
    for (const wi of u.weapons) t += wi.w.cost + (wi.ammo ? wi.ammo.cost : 0);
    for (const up of u.upgrades) t += up.cost;
    return t;
  }

  function frameList(mix) {
    return [].concat(
      Array(mix.heavy).fill("heavy"), Array(mix.medium).fill("medium"), Array(mix.light).fill("light"));
  }

  // ---- rendering ---------------------------------------------------------
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const money = (n) => `${n.toLocaleString("en-US")}$`;
  const circles = (n, label) =>
    `<div class="circles">${Array.from({ length: n }, (_, i) => `<i class="o">${label ? i + 1 : ""}</i>`).join("")}</div>`;
  const cap = (s) => s[0].toUpperCase() + s.slice(1);
  const MIN_ROWS = 5;

  function rowsOf(u) {
    const rows = [];
    for (const wi of u.weapons) {
      let special = wi.w.text;
      let cost = wi.w.cost;
      if (wi.ammo) {
        const note = `${wi.ammo.name}: ${wi.ammo.text}`.replace(/: $/, "");
        special = special ? `${special}; ${note}` : note;
        cost += wi.ammo.cost;
      }
      rows.push([(wi.kind === "melee" ? "(M) " : "") + wi.w.name, wi.w.damage, special, money(cost)]);
    }
    for (const up of u.upgrades) rows.push([up.name, "", applied(up.text, up.effect), money(up.cost)]);
    while (rows.length < MIN_ROWS) rows.push(["", "", "", ""]);
    return rows;
  }

  function tableHead() {
    return `<thead><tr><th class="w">Platforms</th><th class="d">Dmg</th>
        <th class="s">Special</th><th class="c">Cost</th></tr></thead>`;
  }

  function blockHtml(u, n, leader) {
    const plat = rowsOf(u).map(([a, b, c, k]) =>
      `<tr><td class='w'>${esc(a)}</td><td class='d'>${esc(b)}</td><td class='s'>${esc(c)}</td><td class='c'>${esc(k)}</td></tr>`).join("");
    const effects = u.upgrades.map((x) => x.effect).concat(u.perk ? [u.perk.effect || {}] : []);
    const starred = new Set(effects.flatMap((e) => statsOf(EFFECT_STAT, e).concat(statsOf(CONDITIONAL_STAT, e))));
    const star = {};
    for (const k of Object.keys(MARK)) star[k] = starred.has(k) ? MARK[k] : "";
    const notes = u.perk
      ? `<b>Perk &ndash; ${esc(u.perk.name)}:</b> ${esc(applied(u.perk.text, u.perk.effect))} (5 XP)` : "";
    return `
<section class="unit">
  <header><b>${String(n).padStart(2, "0")}</b> &ndash; <span class="sign">${esc(u.name)}</span>${leader ? '<span class="lead">Squad leader</span>' : ""}
    <span class="frame">${cap(u.frame)} frame &middot; ${u.pf} PF${star.PF}</span></header>
  <div class="body">
    <div class="left">
      <div class="stats">
        <div><span>S</span><b>${u.speed}${star.S}</b></div>
        <div><span>CS</span><b>${u.cs}+${star.CS}</b></div>
        <div><span>AR</span><b>${u.ar}+${star.AR}</b></div>
        <div><span>HL</span><b>${u.hl}${star.HL}</b></div>
      </div>
      <div class="trk"><span>Heat tracker</span>${circles(u.hl, true)}</div>
      <div class="trk"><span>HP tracker${star.HP}</span>${circles(u.hp, false)}</div>
    </div>
    <div class="platwrap"><table class="plat">${tableHead()}<tbody>${plat}</tbody></table></div>
  </div>
  <div class="foot2">
    <div class="notes"><span>Notes</span> ${notes}</div>
    <div class="total"><span>Total cost</span> <b>${money(totalCost(u))}</b></div>
  </div>
</section>`;
  }

  const BLANK = { heat: 20, hp: 10, rows: 8 };
  function blankBlockHtml(n) {
    const row = "<tr><td class='w'></td><td class='d'></td><td class='s'></td><td class='c'></td></tr>";
    return `
<section class="unit">
  <header><b>${String(n).padStart(2, "0")}</b> &ndash; <span class="sign">Call sign</span>
    <span class="frame">Frame: L / M / H &middot; PF ___</span></header>
  <div class="body">
    <div class="left">
      <div class="stats">
        <div><span>S</span><b></b></div><div><span>CS</span><b></b></div>
        <div><span>AR</span><b></b></div><div><span>HL</span><b></b></div>
      </div>
      <div class="trk"><span>Heat tracker</span>${circles(BLANK.heat, true)}</div>
      <div class="trk"><span>HP tracker</span>${circles(BLANK.hp, true)}</div>
    </div>
    <div class="platwrap"><table class="plat">${tableHead()}<tbody>${row.repeat(BLANK.rows)}</tbody></table></div>
  </div>
  <div class="foot2">
    <div class="notes"><span>Notes</span></div>
    <div class="total"><span>Total cost</span> <b></b></div>
  </div>
</section>`;
  }

  function pageHtml(blocks) {
    return `<div class="page"><div class="top"><h1>FLAMES OF ORION</h1>
      <div class="f">Combat unit name</div><div class="f">Faction</div><div class="f">Player</div></div>${blocks}</div>`;
  }

  // ---- app ---------------------------------------------------------------
  const $ = (id) => document.getElementById(id);
  const ids = ["seed", "squads", "heavy", "medium", "light", "perk", "ammo", "paper", "blank"];
  const clamp = (v, lo, hi, dflt) => { v = parseInt(v, 10); return Number.isNaN(v) ? dflt : Math.max(lo, Math.min(hi, v)); };

  function readOptions() {
    return {
      seed: $("seed").value.trim() || "1",
      squads: clamp($("squads").value, 1, 64, 2),
      mix: {
        heavy: clamp($("heavy").value, 0, 4, 1),
        medium: clamp($("medium").value, 0, 4, 2),
        light: clamp($("light").value, 0, 4, 1),
      },
      perk: $("perk").checked, ammo: $("ammo").checked,
      paper: $("paper").value, blank: $("blank").checked,
    };
  }

  function render() {
    const o = readOptions();
    const total = o.mix.heavy + o.mix.medium + o.mix.light;
    const warn = $("warn");
    warn.textContent = total === 4 ? "" : `Frames add up to ${total}; a page holds exactly 4 mechs.`;
    $("mix-fields").classList.toggle("bad", total !== 4);
    $("gen-only").hidden = o.blank;
    $("pagesize").textContent = `@page { size: ${o.paper} portrait; margin: 0.3in; }`;
    if (total !== 4) { $("sheets").innerHTML = ""; return; }
    const rng = makeRng(o.seed);
    const frames = frameList(o.mix);
    const pages = [];
    for (let p = 0; p < o.squads; p++) {
      if (o.blank) { pages.push(pageHtml(frames.map((_, i) => blankBlockHtml(i + 1)).join(""))); continue; }
      const units = frames.map((f) => generateMech(f, rng, o));
      if (o.perk) pickPerk(units[0], rng);
      pages.push(pageHtml(units.map((u, i) => blockHtml(u, i + 1, i === 0)).join("")));
    }
    $("sheets").innerHTML = pages.join("");
    try {
      const q = new URLSearchParams({
        seed: o.seed, squads: o.squads, h: o.mix.heavy, m: o.mix.medium, l: o.mix.light,
        perk: +o.perk, ammo: +o.ammo, paper: o.paper, blank: +o.blank,
      });
      history.replaceState(null, "", "#" + q.toString());
    } catch (e) { /* file:// or sandboxed: ignore */ }
  }

  function loadFromHash() {
    const q = new URLSearchParams(location.hash.slice(1));
    const set = (id, k, f = (x) => x) => { if (q.has(k)) $(id).value = f(q.get(k)); };
    set("seed", "seed"); set("squads", "squads"); set("heavy", "h"); set("medium", "m");
    set("light", "l"); set("paper", "paper");
    if (q.has("perk")) $("perk").checked = q.get("perk") === "1";
    if (q.has("ammo")) $("ammo").checked = q.get("ammo") === "1";
    if (q.has("blank")) $("blank").checked = q.get("blank") === "1";
  }

  function randomSeed() {
    return Math.random().toString(36).slice(2, 8);
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("seed").value = randomSeed();
    loadFromHash();
    ids.forEach((id) => $(id).addEventListener("input", render));
    $("reroll").addEventListener("click", () => { $("seed").value = randomSeed(); render(); });
    $("print").addEventListener("click", () => window.print());
    $("copy").addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(location.href); $("copy").textContent = "Copied!"; }
      catch (e) { $("copy").textContent = "Copy the address bar"; }
      setTimeout(() => ($("copy").textContent = "Copy link"), 1500);
    });
    render();
  });
})();
