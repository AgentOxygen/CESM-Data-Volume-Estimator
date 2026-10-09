// Builds a CESM user_nl_* history block from the page's selected rows.
// Pure functions, no DOM: the page calls Namelist.build(), tests/test_namelist.py
// drives the same file under node. Sources for every rule below are in
// notes/cmip7-namelist-export-plan.md (read from the CESM3 source, tag alpha09e).
(function (root) {
  // CMIP7 frequency -> [nhtfrq, mfilt]. Negative nhtfrq = hours; 0 = monthly.
  // -8760 / -87600 assume the 365-day calendar. mfilt is file packaging only.
  // fx and subhr have no entry, so they are dropped and listed.
  const FREQ = { mon: [0, 1], dec: [-87600, 1], yr: [-8760, 1], day: [-24, 30],
                 "6hr": [-6, 120], "3hr": [-3, 240], "1hr": [-1, 720] };
  const ORDER = ["mon", "dec", "yr", "day", "6hr", "3hr", "1hr"];   // tape order: monthly first, then coarse -> fine

  const COMPONENTS = {
    atm: { file: "user_nl_cam", pre: "", flags: "ABILMNSX", maxName: 32, maxTapes: 10,
           empty: "empty_htapes" },
    lnd: { file: "user_nl_clm", pre: "hist_", flags: ["A", "I", "X", "M", "SUM"], maxName: 64, maxTapes: 10,
           empty: "hist_empty_htapes", dov2xy: true },
    // MOSART has no empty_htapes: its default fields stay on, so this file only adds to them.
    rof: { file: "user_nl_mosart", pre: "", flags: "AIXM", maxName: 80, maxTapes: 3, empty: null },
    // CISM: one stream of whole years, a single space-delimited variable string. See buildGlc.
    glc: { file: "user_nl_cism", glc: true },
    // CICE: stream letters in histfreq/histfreq_n, and a per-field f_<name> mask of those letters. See buildIce.
    ice: { file: "user_nl_cice", ice: true },
    // MOM6: not a namelist but an FMS diag_table; this is the unresolved form CESM copies from SourceMods.
    ocn: { file: "diag_table.unresolved", ocn: true },
  };
  const q = (s) => `'${s}'`;
  
  const header = (c, meta) => [
    `! Generated ${meta.date || new Date().toISOString().slice(0, 10)} by the CESM Data Volume Estimator (CMIP7 -> CESM3 variable lists).`,
    `! ${c.file}: history output for the selection on the page.`,
    ...(meta.title ? [`! ${meta.title}`] : [])];

  // CISM writes one history stream every N whole years. The default file takes the coarsest
  // requested frequency; each other expressible frequency gets a variant file to swap in.
  const GLC_YEARS = { yr: 1, dec: 10 };
  function buildGlc(c, rows, meta) {
    const dropped = [], byFreq = {};
    for (const r of rows) {
      if (!GLC_YEARS[r.freq]) { dropped.push({ name: r.name, freq: r.freq, why: "CISM history is whole years: only yr and dec can be written" }); continue; }
      (byFreq[r.freq] ||= new Set()).add(r.name);
    }
    const freqs = Object.keys(byFreq).sort((a, b) => GLC_YEARS[b] - GLC_YEARS[a]);   // coarsest first
    const one = (f, variant) => {
      const L = [...header(c, meta),
        ...(variant ? [`! Writes the ${f} variables only (every ${GLC_YEARS[f]} year(s)). CISM has one history stream per run.`,
                 `! Swap this in for ${c.file} to get ${f} output instead of the default file.`] : []),
        ...(meta.unverified ? [`! ${meta.unverified} line(s) on the page are not verified against a CESM3 run.`] : []),
        `! esm_history_vars REPLACES CISM's default variable list.`];
      for (const d of dropped) L.push(`! not exported: ${d.name} (${d.freq}): ${d.why}`);
      if (!f) return L.concat("! (nothing to export)").join("\n") + "\n";
      return L.concat("", ` esm_history_vars = '${[...byFreq[f]].sort().join(" ")}'`,
                      ` history_option = 'nyears'`, ` history_frequency = ${GLC_YEARS[f]}`).join("\n") + "\n";
    };
    return { text: one(freqs[0]), variants: freqs.slice(1).map(f => ({ freq: f, text: one(f, true) })), dropped };
  }

  // CICE has no field lists. histfreq/histfreq_n define up to 5 streams (letter + interval); each field's
  // f_<name> string lists the letters of the streams it appears on. A stream is found by its LETTER, so two
  // streams that share one (6hr and 3hr are both 'h'; yr and dec both 'y') cannot be told apart: the coarser wins.
  // CICE averages everything: a requested I/M/X is exported but noted. meta.iceFields = the valid f_ names.
  const ICE_STREAM = { mon: ["m", 1], day: ["d", 1], "6hr": ["h", 6], "3hr": ["h", 3], "1hr": ["h", 1], yr: ["y", 1], dec: ["y", 10] };
  function buildIce(c, rows, meta) {
    const valid = new Set(meta.iceFields || []), dropped = [], notes = [], masks = {}, used = {};
    const wanted = new Set(rows.map(r => r.freq));
    const streams = ORDER.filter(f => wanted.has(f) && ICE_STREAM[f]);
    for (const f of streams) {
      const [letter] = ICE_STREAM[f], clash = Object.keys(used).find(g => used[g] === letter);
      if (clash) dropped.push(...rows.filter(r => r.freq === f).map(r => ({ name: r.name, freq: f,
        why: `stream letter '${letter}' is already used by ${clash}; CICE cannot tell them apart` })));
      else used[f] = letter;
    }
    for (const r of rows) {
      if (!ICE_STREAM[r.freq]) { dropped.push({ name: r.name, freq: r.freq, why: `frequency ${r.freq} has no history setting` }); continue; }
      if (!used[r.freq]) continue;                                       // already reported as a clash
      // The spreadsheet's daily names carry a _d suffix on the same f_ variable.
      const v = valid.has(r.name) ? r.name : /_d$/.test(r.name) && valid.has(r.name.slice(0, -2)) ? r.name.slice(0, -2) : "";
      if (!v) { dropped.push({ name: r.name, freq: r.freq, why: "no f_ switch of that name in CICE" }); continue; }
      (masks[v] ||= new Set()).add(used[r.freq]);
      if (r.method && r.method !== "A") notes.push(`! ${v} (${r.freq}): ${r.method} requested but CICE averages every field`);
    }
    const act = streams.filter(f => used[f]);
    const L = [...header(c, meta),
      `! CICE cannot switch its defaults off: fields below are ADDED to the model's default output, and these`,
      `! histfreq/histfreq_n REPLACE its stream layout (a default mask such as 'mdhxx' follows the new letters).`,
      ...(meta.unverified ? [`! ${meta.unverified} line(s) are not verified against a CESM3 run. An unknown f_ name stops namelist read.`] : []),
      ...notes, ...dropped.map(d => `! not exported: ${d.name} (${d.freq}): ${d.why}`)];
    if (!act.length) return { text: L.concat("! (nothing to export)").join("\n") + "\n", dropped };
    const pad = (a, x) => a.concat(Array(5 - a.length).fill(x)).join(", ");
    L.push("", ` histfreq = ${pad(act.map(f => q(used[f])), q("x"))}`,
           ` histfreq_n = ${pad(act.map(f => ICE_STREAM[f][1]), 0)}`);
    for (const v of Object.keys(masks).sort())
      L.push(` f_${v} = ${q(act.map(f => used[f]).filter(l => masks[v].has(l)).join(""))}`);
    return { text: L.join("\n") + "\n", dropped };
  }

  // MOM6 diag_table. One file per (frequency, module); one line per field. [output, new-file, date format] per frequency.
  const MOM_FREQ = { mon: [[1, "months"], [1, "months"], "%4yr-%2mo"], day: [[1, "days"], [1, "months"], "%4yr-%2mo"],
    "6hr": [[6, "hours"], [1, "months"], "%4yr-%2mo"], "3hr": [[3, "hours"], [1, "months"], "%4yr-%2mo"],
    "1hr": [[1, "hours"], [1, "days"], "%4yr-%2mo-%2dy"], yr: [[1, "years"], [1, "years"], "%4yr"],
    dec: [[10, "years"], [10, "years"], "%4yr"] };
  const MOM_TAG = { ocean_model: "native", ocean_model_z: "z", ocean_model_rho2: "rho2" };
  // Time method -> diag_table reduction. A mean and I (".false.") are as in CESM's own template; min/max as its
  // "tos:tos_min:min" entries; sum is not used by the template and is unverified.
  const MOM_RED = { A: ["mean", ""], I: [".false.", "_inst"], X: ["max", "_max"], M: ["min", "_min"], SUM: ["sum", "_sum"] };
  function buildOcn(c, rows, meta) {
    const where = {};                                            // name -> module, native preferred
    for (const m of ["ocean_model_rho2", "ocean_model_z", "ocean_model"]) for (const n of (meta.momFields || {})[m] || []) where[n] = m;
    const dropped = [], notes = [], files = {};
    for (const r of rows) {
      if (!MOM_FREQ[r.freq]) { dropped.push({ name: r.name, freq: r.freq, why: `frequency ${r.freq} has no history setting` }); continue; }
      const mod = where[r.name] || "ocean_model";
      if (!where[r.name]) notes.push(r.name);
      const red = MOM_RED[r.method || "A"][0], tail = MOM_RED[r.method || "A"][1];
      ((files[`${r.freq}|${mod}`] ||= { freq: r.freq, mod, fields: [] }).fields).push({ name: r.name, red, tail });
    }
    const keys = Object.keys(files).sort((a, b) => ORDER.indexOf(files[a].freq) - ORDER.indexOf(files[b].freq) || a.localeCompare(b));
    const L = [`# Generated ${meta.date || new Date().toISOString().slice(0, 10)} by the CESM Data Volume Estimator (CMIP7 -> CESM3 variable lists).`,
      `# ${c.file}: ocean history for the selection on the page. ${meta.title || ""}`,
      `# Copy to SourceMods/src.mom/${c.file} in the case. It REPLACES CESM's default diag_table entirely.`,
      ...(meta.unverified ? [`# ${meta.unverified} line(s) are not verified against a CESM3 run.`] : []),
      ...(notes.length ? [`# ${notes.length} name(s) are not in CESM's diag_table template and go to ocean_model; MOM6 writes them only if it registers them.`] : []),
      ...dropped.map(d => `# not exported: ${d.name} (${d.freq}): ${d.why}`)];
    if (!keys.length) return { text: L.concat("# (nothing to export)").join("\n") + "\n", dropped };
    const fname = (f) => `"\${CASE}.mom6.h.${f.freq}.${MOM_TAG[f.mod]}.${MOM_FREQ[f.freq][2]}"`;
    L.push("", `"MOM6 diagnostic fields table for CESM case: \${CASE}"`, "1 1 1 0 0 0", "", "### Section-1: File List");
    for (const k of keys) {
      const f = files[k], [[n, u], [nn, nu]] = MOM_FREQ[f.freq];
      L.push(`${fname(f)}, ${n}, "${u}", 1, "days", "time", ${nn}, "${nu}"`);
    }
    L.push("", "### Section-2: Fields List");
    for (const k of keys) {
      const f = files[k];
      L.push(`# ${fname(f)}`);
      const seen = new Set();
      for (const x of f.fields.sort((a, b) => a.name.localeCompare(b.name) || a.tail.localeCompare(b.tail))) {
        let alias = x.name + x.tail;                       // a second method on one field needs its own output name
        if (seen.has(alias)) continue;
        seen.add(alias);
        L.push(`"${f.mod}", "${x.name}", "${alias}", ${fname(f)}, "all", "${x.red}", "none", 2`);
      }
      L.push("");
    }
    return { text: L.join("\n") + "\n", dropped };
  }

  // rows: [{name, method, freq, items}]  ->  {text, tapes, dropped} | {error}
  function build(comp, rows, meta = {}) {
    const c = COMPONENTS[comp];
    if (!c) return { error: `no namelist generator for ${comp}` };
    if (c.glc) return buildGlc(c, rows, meta);
    if (c.ice) return buildIce(c, rows, meta);
    if (c.ocn) return buildOcn(c, rows, meta);
    const dropped = [], byFreq = {};
    for (const r of rows) {
      const why = !FREQ[r.freq] ? `frequency ${r.freq} has no history setting`
        : r.name.length > c.maxName ? `name longer than ${c.maxName} characters`
        : r.method && !c.flags.includes(r.method) ? `averaging flag ${r.method} not valid for ${comp}` : "";
      if (why) { dropped.push({ name: r.name, freq: r.freq, why }); continue; }
      // A name may appear once per tape; a second method at the same frequency opens another tape.
      const tapes = (byFreq[r.freq] ||= []);
      let t = tapes.find(x => !x.names.has(r.name));
      if (!t) tapes.push(t = { freq: r.freq, names: new Set(), entries: [] });
      t.names.add(r.name);
      t.entries.push(r.method ? `${r.name}:${r.method}` : r.name);
    }
    const tapes = ORDER.flatMap(f => byFreq[f] || []);
    if (tapes.length > c.maxTapes) {
      return { error: `${comp} needs ${tapes.length} history tapes (${tapes.map(t => t.freq).join(", ")}); ` +
                      `${c.file} allows ${c.maxTapes}. Drop a frequency.` };
    }
    const L = [...header(c, meta),
               c.empty ? `! ${c.empty} = .true. DISCARDS ${comp}'s default output: only the fields below are written.`
                       : `! ${comp} cannot switch its defaults off: the fields below are ADDED to the model's default output.`,
               ...(meta.unverified ? [`! ${meta.unverified} line(s) are not verified against a CESM3 run. An unknown`,
                                      `! name in a fincl list aborts the run at initialisation.`] : []),
               `! nhtfrq assumes a 365-day calendar for yr and dec. Unverified by running a case.`];
    for (const d of dropped) L.push(`! not exported: ${d.name} (${d.freq}): ${d.why}`);
    if (!tapes.length) return { text: L.concat("! (nothing to export)").join("\n") + "\n", tapes, dropped };
    L.push("", ...(c.empty ? [` ${c.empty} = .true.`] : []),
           ` ${c.pre}nhtfrq = ${tapes.map(t => FREQ[t.freq][0]).join(", ")}`,
           ` ${c.pre}mfilt = ${tapes.map(t => FREQ[t.freq][1]).join(", ")}`);
    if (c.dov2xy) L.push(` ${c.pre}dov2xy = ${tapes.map(() => ".true.").join(", ")}`);
    tapes.forEach((t, i) => {
      L.push("", `! h${i} -- ${t.freq}`);
      t.entries.sort().forEach((e, k) =>
        L.push(` ${k ? "   " : `${c.pre}fincl${i + 1} = `}${q(e)}${k < t.entries.length - 1 ? "," : ""}`));
    });
    return { text: L.join("\n") + "\n", tapes, dropped };
  }

  // Uncompressed ("stored") zip: [{name, text}] -> Uint8Array. No dependency; CRC-32 is the only arithmetic.
  const CRC = Array.from({ length: 256 }, (_, n) => { for (let k = 0; k < 8; k++) n = n & 1 ? 0xEDB88320 ^ (n >>> 1) : n >>> 1; return n >>> 0; });
  const crc32 = (b) => { let c = ~0; for (const x of b) c = CRC[(c ^ x) & 255] ^ (c >>> 8); return ~c >>> 0; };
  function zip(files, now = new Date()) {
    const enc = new TextEncoder(), parts = [], central = [];
    const dosTime = (now.getHours() << 11) | (now.getMinutes() << 5) | (now.getSeconds() >> 1);
    const dosDate = ((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate();
    let offset = 0;
    for (const f of files) {
      const name = enc.encode(f.name), data = enc.encode(f.text), crc = crc32(data);
      const h = new DataView(new ArrayBuffer(30));          // local file header
      [[0, 0x04034b50, 4], [4, 20, 2], [6, 0x0800, 2], [8, 0, 2], [10, dosTime, 2], [12, dosDate, 2], [14, crc, 4],
       [18, data.length, 4], [22, data.length, 4], [26, name.length, 2], [28, 0, 2]].forEach(([o, v, n]) => n == 4 ? h.setUint32(o, v, true) : h.setUint16(o, v, true));
      const e = new DataView(new ArrayBuffer(46));          // central directory entry
      [[0, 0x02014b50, 4], [4, 20, 2], [6, 20, 2], [8, 0x0800, 2], [10, 0, 2], [12, dosTime, 2], [14, dosDate, 2], [16, crc, 4],
       [20, data.length, 4], [24, data.length, 4], [28, name.length, 2], [30, 0, 2], [32, 0, 2], [34, 0, 2], [36, 0, 2],
       [38, 0, 4], [42, offset, 4]].forEach(([o, v, n]) => n == 4 ? e.setUint32(o, v, true) : e.setUint16(o, v, true));
      parts.push(new Uint8Array(h.buffer), name, data);
      central.push(new Uint8Array(e.buffer), name);
      offset += 30 + name.length + data.length;
    }
    const size = central.reduce((n, p) => n + p.length, 0);
    const end = new DataView(new ArrayBuffer(22));
    [[0, 0x06054b50, 4], [8, files.length, 2], [10, files.length, 2], [12, size, 4], [16, offset, 4]]
      .forEach(([o, v, n]) => n == 4 ? end.setUint32(o, v, true) : end.setUint16(o, v, true));
    const all = [...parts, ...central, new Uint8Array(end.buffer)], out = new Uint8Array(offset + size + 22);
    let at = 0; for (const p of all) { out.set(p, at); at += p.length; }
    return out;
  }

  // Every file for a component: the main namelist plus any variants. Errors become an entry the user will see.
  function files(comp, rows, meta) {
    const o = build(comp, rows, meta), c = COMPONENTS[comp];
    if (o.error) return [{ name: `${c.file}.ERROR.txt`, text: o.error + "\n" }];
    return [{ name: c.file, text: o.text }, ...(o.variants || []).map(v => ({ name: `variants/${c.file}.${v.freq}`, text: v.text }))];
  }

  root.Namelist = { build, files, zip, COMPONENTS, FREQ };
  if (typeof module !== "undefined") module.exports = root.Namelist;
})(typeof window !== "undefined" ? window : globalThis);
