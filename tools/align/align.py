#!/usr/bin/env python3
"""Align JLPT listening scripts to faster-whisper word timestamps (sentence level).

  align.py build ITEMS.json WORDS_DIR OUT.js [STATS.json [META.json]]
      WORDS_DIR holds <LEVEL>/<id>.json files written by transcribe.py:
        {"path": item.path, "duration": sec, "words": [[start, end, "word"], ...]}
      writes  window.SHADOW_JLPT={N3:{'<item.path>':[[s,e,'text'],...]},N2:{...},N1:{...}};

Method: the script is split into sentences (。？！ and line breaks; speaker labels such as 女：/男：/(1) 男：
are removed). Script and recognised text are both normalised to hiragana (pykakasi, NFKC, punctuation and
spaces dropped) keeping a map back to the sentence / to the word timestamps. difflib finds the matching
character blocks; every sentence takes the time of its first and last matched character. Sentences with too
few matched characters or an implausible speaking rate are dropped.
"""
import difflib
import json
import os
import re
import sys
import unicodedata

try:
    import pykakasi
    _KKS = pykakasi.kakasi()
except Exception:  # pragma: no cover - fall back to kana-only normalisation
    _KKS = None

MIN_RATIO = 0.5        # matched chars / sentence chars
MIN_MATCHED = 2
MIN_BLOCK = 2          # ignore difflib matches shorter than this (noise)
SEC_PER_CHAR_MIN = 0.04
SEC_PER_CHAR_MAX = 0.6
PAD_START = 0.12
PAD_END = 0.25

LABEL_RE = re.compile(
    r'^\s*(?:[（(]?(?:例|\d+|[０-９]+)[)）]?\s*)?'      # (1) / (例) / 例1 prefixes
    r'(?:例\s*\d+\s*)?'
    r'[○●◯]?\s*'
    r'[^\s：:。、？！?!「」]{1,8}?\s*[：:]\s*')          # 女： 男2： 店員(男)： アナウンサー：
ENUM_RE = re.compile(r'^\s*(?:[①-⑳]|[（(]\s*\d+\s*[)）]|\d{1,2}\s*[.．、)）]|[０-９]{1,2}\s*[.．、)）]|[\d０-９]{1,2}\s+)\s*')
SPLIT_RE = re.compile(r'(?<=[。？！?!])')


def split_sentences(script):
    out = []
    for line in script.replace('\r', '').split('\n'):
        line = line.strip()
        if not line:
            continue
        line = LABEL_RE.sub('', line, count=1)
        for s in SPLIT_RE.split(line):
            s = ENUM_RE.sub('', s.strip()).strip()
            if s and norm_chars(s):
                out.append(s)
    return out


def _kata2hira(c):
    o = ord(c)
    return chr(o - 0x60) if 0x30A1 <= o <= 0x30F6 else c


def _keep(c):
    if c == 'ー':
        return True
    cat = unicodedata.category(c)
    return cat[0] in 'LN'


def norm_chars(text):
    """-> list of (hira_char, orig_start, orig_end); offsets are float positions in `text`."""
    text = unicodedata.normalize('NFKC', text)
    res = []
    tokens = _KKS.convert(text) if _KKS else [{'orig': text, 'hira': text}]
    pos = 0
    for t in tokens:
        orig = t['orig']
        j = text.find(orig, pos) if orig else pos
        if j < 0:
            j = pos
        a, b = j, j + len(orig)
        pos = b
        if not orig:
            continue
        hira = t.get('hira') or orig
        has_kanji = any('\u4e00' <= c <= '\u9fff' or c == '々' for c in orig)
        if not has_kanji:
            # keep a 1:1 char mapping when no reading conversion was needed
            for k, c in enumerate(orig):
                c = _kata2hira(c.lower())
                if _keep(c):
                    res.append((c, a + k, a + k + 1))
            continue
        chars = [_kata2hira(c.lower()) for c in hira]
        chars = [c for c in chars if _keep(c)]
        n = len(chars)
        for k, c in enumerate(chars):
            res.append((c, a + (b - a) * k / n, a + (b - a) * (k + 1) / n))
    return res


def _whisper_stream(words):
    """words [[s,e,w],...] -> (hira string, list of (t_start, t_end) per char)."""
    text = ''
    spans = []  # (char_start, char_end, s, e)
    for wd in words:  # [start, end, word] or [start, end, word, probability]
        s, e, w = wd[0], wd[1], wd[2]
        w = unicodedata.normalize('NFKC', w)
        spans.append((len(text), len(text) + len(w), float(s), float(e)))
        text += w
    chars = norm_chars(text)
    # NFKC already applied, so offsets refer to `text`
    times = []
    for _, a, b in chars:
        times.append((_time_at(spans, a, True), _time_at(spans, b, False)))
    return ''.join(c for c, _, _ in chars), times


def _time_at(spans, off, left):
    # find span containing offset (left: off in [cs,ce), right: off in (cs,ce])
    lo, hi = 0, len(spans) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        cs, ce, _, _ = spans[mid]
        if (off < ce) if left else (off <= ce):
            hi = mid
        else:
            lo = mid + 1
    cs, ce, s, e = spans[lo]
    if ce <= cs:
        return s if left else e
    f = min(max((off - cs) / (ce - cs), 0.0), 1.0)
    return s + (e - s) * f


def align(script, words, duration=None):
    """-> list of [start, end, text] for confidently aligned sentences (rounded to 0.01 s)."""
    sents = split_sentences(script)
    if not sents or not words:
        return []
    a_chars, a_sid = [], []
    for i, s in enumerate(sents):
        for c, _, _ in norm_chars(s):
            a_chars.append(c)
            a_sid.append(i)
    a = ''.join(a_chars)
    b, btimes = _whisper_stream(words)
    if not a or not b:
        return []
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    match = [None] * len(a)
    for blk in sm.get_matching_blocks():
        if blk.size >= MIN_BLOCK:
            for k in range(blk.size):
                match[blk.a + k] = blk.b + k
    per = [[] for _ in sents]
    total = [0] * len(sents)
    for ai, sid in enumerate(a_sid):
        total[sid] += 1
        if match[ai] is not None:
            per[sid].append((ai, match[ai]))
    raw = []
    for i, s in enumerate(sents):
        m = per[i]
        n = total[i]
        if len(m) < MIN_MATCHED or len(m) / n < MIN_RATIO:
            raw.append(None)
            continue
        first_ai = a_sid.index(i)
        last_ai = first_ai + n - 1
        st = btimes[m[0][1]][0]
        en = btimes[m[-1][1]][1]
        # unmatched chars at the sentence edges: extend at a typical speaking rate
        st -= (m[0][0] - first_ai) * 0.12
        en += (last_ai - m[-1][0]) * 0.12
        dur = en - st
        if dur <= 0 or dur < SEC_PER_CHAR_MIN * n or dur > SEC_PER_CHAR_MAX * n + 1.5:
            raw.append(None)
            continue
        raw.append([st, en, s])
    # monotonic order, padding limited by the neighbours, clamp to the audio
    out = []
    kept = [r for r in raw if r]
    dur_audio = duration or max(float(w[1]) for w in words) + 1.0
    prev_end = 0.0
    for k, r in enumerate(kept):
        st, en, s = r
        if st < prev_end - 0.05:
            continue  # out of order / overlapping -> unreliable
        if en > dur_audio + 0.3:
            continue  # extrapolated past the end of the audio
        nxt = kept[k + 1][0] if k + 1 < len(kept) else dur_audio
        st = max(prev_end, st - PAD_START, 0.0)
        en = min(en + PAD_END, max(en, (en + nxt) / 2), dur_audio)
        if en - st < 0.2:
            continue
        out.append([round(st, 2), round(en, 2), s])
        prev_end = en
    return out


def js_str(s):
    return "'" + s.replace('\\', '\\\\').replace("'", "\\'").replace('\n', ' ').replace('\u2028', ' ').replace('\u2029', ' ') + "'"


def to_js(data):
    parts = []
    for lv, items in data.items():
        rows = []
        for path, segs in items.items():
            rows.append(js_str(path) + ':[' + ','.join('[%s,%s,%s]' % (_num(s), _num(e), js_str(t)) for s, e, t in segs) + ']')
        parts.append(lv + ':{\n' + ',\n'.join(rows) + '\n}')
    return 'window.SHADOW_JLPT={' + ',\n'.join(parts) + '};\n'


def _num(x):
    s = ('%.2f' % x).rstrip('0').rstrip('.')
    return s or '0'


def build(items_json, words_dir, out_js, stats_json=None, meta_json=None):
    from hashlib import sha1
    items = json.load(open(items_json, encoding='utf-8'))
    data, stats, meta = {}, {}, {}
    for lv, lst in items.items():
        data[lv] = {}
        meta[lv] = {}
        st = stats[lv] = {'items': len(lst), 'transcribed': 0, 'aligned': 0, 'sentences': 0, 'sentences_aligned': 0}
        for it in lst:
            nsent = len(split_sentences(it['script']))
            st['sentences'] += nsent
            f = os.path.join(words_dir, lv, sha1(it['path'].encode('utf-8')).hexdigest() + '.json')
            if not os.path.isfile(f):
                continue
            w = json.load(open(f, encoding='utf-8'))
            st['transcribed'] += 1
            segs = align(it['script'], w['words'], w.get('duration'))
            meta[lv][it['path']] = {'duration': w.get('duration'), 'model': w.get('model'), 'words': len(w['words']),
                                    'sentences': nsent, 'aligned': len(segs)}
            if segs:
                data[lv][it['path']] = segs
                st['aligned'] += 1
                st['sentences_aligned'] += len(segs)
        st['item_coverage'] = round(100 * st['aligned'] / max(1, st['items']), 1)
        st['sentence_coverage'] = round(100 * st['sentences_aligned'] / max(1, st['sentences']), 1)
    with open(out_js, 'w', encoding='utf-8') as fo:
        fo.write(to_js(data))
    if stats_json:
        json.dump(stats, open(stats_json, 'w', encoding='utf-8'), indent=1)
    if meta_json:
        json.dump(meta, open(meta_json, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    print(json.dumps(stats, indent=1))


if __name__ == '__main__':
    if len(sys.argv) in (5, 6, 7) and sys.argv[1] == 'build':
        build(*sys.argv[2:])
    else:
        sys.exit(__doc__)
