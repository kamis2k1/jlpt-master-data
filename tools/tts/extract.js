#!/usr/bin/env node
// Extract every string the app speaks with TTS (VOICE-CONTRACT.md) -> tools/tts/sentences/<LV>.json
//   usage: node tools/tts/extract.js <app www dir> [out dir] [--raw raw.json]
// Output: [{k, t}] per level N1, N2, N3 and K (kaiwa, level independent).
//   k = key(spoken string) (tools/tts/textkey.js)
//   t = text for synthesis. It may keep furigana markup {漢字|かな}: tools/tts/synth.py reads the kanji text and
//       swaps a marked word for its kana only when VOICEVOX would read it differently. Plain kana for words.
// Several keys may share the same t (aliases); the synthesiser makes one clip and stores it under every key.
//
// What the app speaks (app branch round12, www/):
//  index.html  speak() via [data-say] and direct calls
//    - vocab list / detail / flashcard: v.r (reading)                       -> key(v.r) (+ alias key(v.w)), t = v.r
//    - vocab examples: v.ex[i][0]                                            -> t = text
//    - kanji detail: c.rd[i] when c.rd[i] && c.wm, else c.ex[i]              -> words: t = kana reading when known
//    - grammar examples p.ex[i] (furigana p.exf[i]); translation answers p.tr[i][1] (furigana p.trf[i])
//    - test explanations (D.tests, q.vi present): stem with （　） filled by the right option, then （） removed
//  reading.js  "Đọc to" reads the passage; voiced per sentence: paragraphs (/\n\s*\n/), lines (\n / <br>,
//              notice blocks and table cells) and sentences (split after 。？！?!) - see readingPieces()
//  kaiwa.js    sayP(mk) speaks sayText(mk) = plainT(mk).replace(/\s*—\s*/g,'。 '):
//    - every lesson line ln.jp, line pairs A+'　—　'+B (shadowing), lesson vocab v.w (data-say), phrases
//      plainT(p.jp).replace(/〜/g,'') (data-say)                                -> level K
//    - shadowing from reading passages (level packs): sentences 8..45 chars, paragraphs 40..220 chars
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { norm, key, RB } = require('./textkey');

const www = process.argv[2];
if (!www) { console.error('usage: extract.js <www dir> [out dir] [--raw raw.json]'); process.exit(2); }
const outDir = process.argv[3] && !process.argv[3].startsWith('--') ? process.argv[3] : path.join(__dirname, 'sentences');
const rawIdx = process.argv.indexOf('--raw');
const rawOut = rawIdx > 0 ? process.argv[rawIdx + 1] : null;

const W = {}; W.window = W; vm.createContext(W);
for (const f of ['data.js', 'data_n2.js', 'data_n3.js', 'kaiwa_data.js', 'read_n1.js', 'read_n2.js', 'read_n3.js'])
  vm.runInContext(fs.readFileSync(path.join(www, f), 'utf8'), W, { filename: f });
const ALLV = { N1: W.N1DATA, N2: (W.NDATA || {}).N2, N3: (W.NDATA || {}).N3 };

// ---------- helpers (same regexes as the app) ----------
const plainT = s => String(s || '').replace(RB, '$1');                         // kaiwa.js / reading.js
const sayText = mk => plainT(mk).replace(/\s*—\s*/g, '。 ');                   // kaiwa.js
// index.html furigana markup 漢字{かな} -> {漢字|かな} (kaiwa.js sf2kw)
const sf2kw = s => String(s || '').replace(/([^\s{}|]*?)([㐀-鿿豈-﫿々〆ヶ]+)\{([^}|]*)\}/g, (m, pre, k, r) => pre + '{' + k + '|' + r + '}');
const KANJI = /[㐀-鿿豈-﫿々〆ヶ]/;
const kata2hira = s => String(s || '').replace(/[ァ-ヶ]/g, c => String.fromCharCode(c.charCodeAt(0) - 0x60));
// does `reading` fit `word` (kana of the word appear in order, kanji runs take >=1 char)?
function readingFits(word, reading) {
  if (!word || !reading || !KANJI.test(word)) return false;
  if (/[^ぁ-ゖァ-ヺー㐀-鿿豈-﫿々〆ヶ・]/.test(word)) return false;
  const re = '^' + [...word.matchAll(/([㐀-鿿豈-﫿々〆ヶ]+)|([^㐀-鿿豈-﫿々〆ヶ]+)/g)]
    .map(m => m[1] ? '.+' : kata2hira(m[2]).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('') + '$';
  return new RegExp(re).test(kata2hira(reading.replace(/[\s.・]/g, '')));
}
// markup for synthesis: mk must have the same plain text as spoken string s, otherwise use s
const withFuri = (s, mk) => (mk && norm(mk) === norm(s)) ? mk : s;
const cleanT = t => String(t).replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim();

// ---------- collector ----------
const OUT = { N1: new Map(), N2: new Map(), N3: new Map(), K: new Map() };
const RAW = new Set();
const STAT = {};
function add(lv, spoken, synth, src) {
  RAW.add(spoken);
  const k = key(spoken);
  STAT[lv + ':' + src] = (STAT[lv + ':' + src] || 0) + 1;
  if (!k) return;
  if (!/[ぁ-ゖァ-ヺ㐀-鿿豈-﫿々〆ヶ0-9０-９A-Za-zＡ-Ｚａ-ｚ]/.test(norm(spoken))) return; // nothing to read
  const m = OUT[lv];
  if (!m.has(k)) m.set(k, { k, t: cleanT(synth == null ? spoken : synth) });
}

// ---------- reading passages (reading.js bodyHtml / textMap) ----------
function decodeEnt(s) {
  return s.replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos|nbsp);/gi, (m, e) => {
    const l = e.toLowerCase();
    if (l[0] === '#') return String.fromCodePoint(l[1] === 'x' ? parseInt(l.slice(2), 16) : parseInt(l.slice(1), 10));
    return { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' }[l];
  });
}
// split a text (furigana markup kept) into sentences after 。？！?! (kaiwa.js uses /(?<=[。？！])/)
const sentences = s => s.split(/(?<=[。？！?!])/).map(x => x.trim()).filter(Boolean);
// pieces of a passage that get their own clip: every line, and every sentence of a line / paragraph
function readingPieces(r) {
  const out = [];
  const push = s => { s = s.trim(); if (s) out.push(s); };
  if (r.kind === 'notice') {
    // block level boundaries of the rendered poster: br, h3/h4, div, p, li, tr, th/td
    const txt = decodeEnt(String(r.body || '')
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/<\/?(div|p|h\d|li|ul|ol|table|thead|tbody|tr|th|td|hr)\b[^>]*>/gi, '\n')
      .replace(/<(?!\/?ruby|\/?rt)[^>]*>/g, ''));
    txt.split(/\n+/).forEach(line => { push(line); sentences(line).forEach(push); });
  } else {
    String(r.body || '').split(/\n\s*\n/).forEach(p => {
      p = p.trim(); if (!p) return;
      sentences(p).forEach(s => { push(s); s.split(/\n/).forEach(push); });  // kaiwa sentences + line pieces
      p.split(/\n/).forEach(line => sentences(line).forEach(push));
    });
  }
  return out;
}

// ---------- levels ----------
for (const lv of ['N1', 'N2', 'N3']) {
  const D = ALLV[lv];
  // vocab
  for (const v of D.vocab || []) {
    const rd = v.r || '';
    if (rd) { add(lv, rd, rd, 'vocab'); if (v.w && v.w !== rd) add(lv, v.w, rd, 'vocab-w'); }
    for (const e of v.ex || []) if (e && e[0]) add(lv, e[0], e[0], 'vocab-ex');
  }
  // kanji
  for (const c of D.kanji || []) {
    (c.ex || []).forEach((e, i) => {
      const rd = c.rd && c.rd[i];
      if (rd && c.wm) { add(lv, rd, rd, 'kanji'); if (e && e !== rd) add(lv, e, rd, 'kanji-w'); }
      else if (e) add(lv, e, rd && readingFits(e, rd) ? rd : e, 'kanji');
    });
  }
  // grammar
  for (const p of D.grammar || []) {
    (p.ex || []).forEach((e, i) => e && add(lv, e, withFuri(e, sf2kw((p.exf || [])[i])), 'grammar-ex'));
    (p.tr || []).forEach((t, i) => t && t[1] && add(lv, t[1], withFuri(t[1], sf2kw((p.trf || [])[i])), 'grammar-tr'));
  }
  // test explanations (index.html qXp, D.tests only)
  for (const t of D.tests || []) for (const q of t.qs || []) {
    if (!q.vi || !q.opts || !q.a) continue;
    const opt = q.opts[q.a - 1];
    const full = q.stem.replace(/（\s*）|（　+）/, '（' + opt + '）');
    const say = full.replace(/[（）]/g, '');
    let mk = null;
    if (q.furi) {
      const rd = (q.read || [])[q.a - 1];
      const o2 = rd && readingFits(opt, rd) ? '{' + opt + '|' + rd + '}' : opt;
      mk = sf2kw(q.furi).replace(/（\s*）|（　+）/, '（' + o2 + '）').replace(/[（）]/g, '');
    }
    add(lv, say, withFuri(say, mk), 'test');
  }
  // reading passages
  for (const r of (W.READ_DATA || {})[lv] || []) {
    readingPieces(r).forEach(s => add(lv, s, s, 'reading'));
    // kaiwa.js shadowing from reading: long paragraphs 40..220 chars (pool p, not notices)
    if (r.pool === 'p' && r.kind !== 'notice' && r.body)
      String(r.body).split(/\n\s*\n/).forEach(p => { p = p.trim(); const l = plainT(p).length; if (l >= 40 && l <= 220) add(lv, p, p, 'reading-para'); });
  }
}
// ---------- kaiwa (level K) ----------
for (const L of W.KAIWA || []) {
  for (const sc of L.scenes || []) {
    const ls = sc.lines || [];
    ls.forEach(ln => ln.jp && add('K', sayText(ln.jp), ln.jp, 'line'));
    for (let i = 0; i + 1 < ls.length; i += 2) {
      const mk = ls[i].jp + '　—　' + ls[i + 1].jp;
      const a = ls[i].jp.trim(), t = a + (/[。？！?!…」]$/.test(a) ? ' ' : '。') + ls[i + 1].jp;
      add('K', sayText(mk), t, 'pair');
      add('K', mk, t, 'pair-raw');
    }
  }
  for (const v of L.vocab || []) if (v.w) add('K', v.w, v.r && readingFits(v.w, v.r) ? v.r : v.w, 'vocab');
  for (const p of L.phrases || []) if (p.jp) { const s = plainT(p.jp).replace(/〜/g, ''); add('K', s, p.jp.replace(/〜/g, ''), 'phrase'); }
}

fs.mkdirSync(outDir, { recursive: true });
for (const lv of Object.keys(OUT)) {
  const arr = [...OUT[lv].values()];
  fs.writeFileSync(path.join(outDir, lv + '.json'), '[\n' + arr.map(x => JSON.stringify(x)).join(',\n') + '\n]\n');
  const uniq = new Set(arr.map(x => x.t)).size;
  console.log(lv, arr.length, 'keys', uniq, 'clips', arr.reduce((a, x) => a + norm(x.t).length, 0), 'chars');
}
console.log(JSON.stringify(STAT));
if (rawOut) fs.writeFileSync(rawOut, JSON.stringify([...RAW]));
