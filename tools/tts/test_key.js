#!/usr/bin/env node
// Parity of norm()/key() between tools/tts/textkey.js and tools/tts/textkey.py.
//   usage: node tools/tts/test_key.js RAW.json [N]   (RAW.json from: extract.js <www> <out> --raw RAW.json)
// Checks N (default 1000) random spoken strings plus hand-made edge cases.
'use strict';
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');
const { norm, key } = require('./textkey');

const raw = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const N = +(process.argv[3] || 1000);
let seed = 12345;
const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
const pick = [];
for (let i = 0; i < N && raw.length; i++) pick.push(raw[Math.floor(rnd() * raw.length)]);
const edge = [
  '', '   ', '　', '{漢字|かんじ}を<b>書く</b>。', 'a b c　d\te\nf\r\ng h i﻿j k l m\u000bn\u000co',
  'ká', 'ガ', 'が', 'がき', '<br>改行<br/>テスト', '{{x|y}}', '{a|b|c}', '<a href="x">リンク</a>', 'x<y>z',
  '\u001c\u001d\u001e\u001f区切り', '\u0085次', '​幅ゼロ', 'Ａ：もしもし', '①大変だけどやるしかないよ。', '𠮷野家', '〜から{熱|ねつ}があります',
];
const all = pick.concat(edge);
const py = JSON.parse(execFileSync('python3', ['-I', path.join(__dirname, 'textkey.py')], { input: JSON.stringify(all), maxBuffer: 1 << 28 }).toString());
let bad = 0;
all.forEach((s, i) => {
  const [pn, pk] = py[i];
  if (pn !== norm(s) || pk !== key(s)) { bad++; if (bad <= 10) console.log('MISMATCH', JSON.stringify(s), JSON.stringify(norm(s)), JSON.stringify(pn)); }
});
console.log(`${all.length} strings (${pick.length} sampled + ${edge.length} edge cases): ${bad} mismatches`);
process.exit(bad ? 1 : 0);
