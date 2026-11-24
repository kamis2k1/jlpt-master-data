// Text key for VOICEVOX voice packs (VOICE-CONTRACT.md, "Text key"). The app computes the same key.
//   norm(t): {漢字|かな} -> 漢字; strip HTML tags; NFC; remove all whitespace (the JS \s set).
//   key(t)  = first 16 hex chars of SHA-256(UTF-8(norm(t))). Empty norm -> no audio.
// tools/tts/textkey.py is the Python twin (parity checked by tools/tts/test_key.sh).
'use strict';
const crypto = require('crypto');
const RB = /\{([^|{}]+)\|([^{}]+)\}/g;
function norm(t) {
  return String(t == null ? '' : t).replace(RB, '$1').replace(/<[^>]*>/g, '').normalize('NFC').replace(/\s+/g, '');
}
function key(t) {
  const n = norm(t);
  return n ? crypto.createHash('sha256').update(n, 'utf8').digest('hex').slice(0, 16) : '';
}
module.exports = { norm, key, RB };
