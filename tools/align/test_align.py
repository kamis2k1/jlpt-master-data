#!/usr/bin/env python3
"""Unit test for align.py with synthetic whisper word lists built from real scripts.

Run: python tools/align/test_align.py   (needs pykakasi)
"""
import json
import os
import random
import subprocess
import sys
import tempfile
from hashlib import sha1

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import align  # noqa: E402

try:
    import pykakasi
    KKS = pykakasi.kakasi()
except Exception:
    KKS = None


def fake_words(script, rng, noise=True):
    """Pretend whisper output: tokens of each sentence with times, pauses between sentences,
    random kanji->kana rewrites, dropped tokens and inserted junk. Returns (words, truth)."""
    t = 1.0
    words, truth = [], []
    words.append([0.2, 0.8, '1番'])
    for s in align.split_sentences(script):
        toks = KKS.convert(s) if KKS else [{'orig': s, 'hira': s}]
        st = t
        for tk in toks:
            w = tk['orig']
            n = max(1, len(tk['hira']))
            d = 0.11 * n
            if noise and rng.random() < 0.15:
                w = tk['hira']           # recogniser wrote kana instead of kanji
            if noise and rng.random() < 0.05:
                t += d                    # word missing from the transcript
                continue
            if noise and rng.random() < 0.03:
                words.append([t, t + 0.3, 'えー'])
                t += 0.3
            words.append([round(t, 2), round(t + d, 2), w])
            t += d
        truth.append((st, t, s))
        t += rng.uniform(0.3, 1.2)
    return words, truth, t + 1


def check_item(script, rng):
    words, truth, dur = fake_words(script, rng)
    segs = align.align(script, words, dur)
    tmap = {}
    for a, b, s in truth:
        tmap.setdefault(s, []).append((a, b))  # the same sentence can occur twice (question repeated)
    errs = []
    prev = 0
    for s, e, txt in segs:
        assert s < e, (s, e, txt)
        assert 0 <= s and e <= dur, (s, e, dur)
        assert s >= prev - 1e-6, 'not monotonic'
        prev = e
        errs.append(min(max(abs(s - a), abs(e - b)) for a, b in tmap[txt]))
    return len(segs), len(truth), errs


def main():
    items = json.load(open(os.path.join(HERE, 'items.json'), encoding='utf-8'))
    rng = random.Random(7)
    tot_seg = tot_sent = 0
    allerr = []
    for lv in items:
        for it in rng.sample(items[lv], 15):
            n, m, errs = check_item(it['script'], rng)
            tot_seg += n
            tot_sent += m
            allerr += errs
    allerr.sort()
    p50 = allerr[len(allerr) // 2]
    p95 = allerr[int(len(allerr) * 0.95)]
    print(f'aligned {tot_seg}/{tot_sent} sentences, boundary error p50={p50:.2f}s p95={p95:.2f}s max={allerr[-1]:.2f}s')
    assert tot_seg >= 0.8 * tot_sent, 'coverage too low'
    assert p95 < 0.8 and allerr[-1] < 3, 'boundaries too far off'

    # garbage transcript must give (almost) nothing
    it = items['N3'][0]
    junk = [[i * 0.5, i * 0.5 + 0.4, w] for i, w in enumerate('ありがとう ございました 天気 いい です ね 東京 大阪'.split() * 3)]
    bad = align.align(it['script'], junk, 30)
    print('junk transcript ->', len(bad), 'sentences')
    assert len(bad) <= 1

    # end-to-end build + JS output loads in node
    with tempfile.TemporaryDirectory() as d:
        sub = {lv: items[lv][:3] for lv in items}
        json.dump(sub, open(os.path.join(d, 'items.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        for lv, lst in sub.items():
            os.makedirs(os.path.join(d, 'w', lv))
            for it in lst:
                words, _, dur = fake_words(it['script'], rng)
                json.dump({'path': it['path'], 'duration': dur, 'words': words},
                          open(os.path.join(d, 'w', lv, sha1(it['path'].encode()).hexdigest() + '.json'), 'w', encoding='utf-8'),
                          ensure_ascii=False)
        out = os.path.join(d, 'shadow_jlpt.js')
        align.build(os.path.join(d, 'items.json'), os.path.join(d, 'w'), out, os.path.join(d, 'stats.json'))
        js = ("global.window={};require(process.argv[1]);const S=window.SHADOW_JLPT;"
              "for(const lv of ['N3','N2','N1']){const k=Object.keys(S[lv]);if(!k.length)throw lv;"
              "for(const p of k){if(!p.startsWith('../'))throw p;for(const [s,e,t] of S[lv][p]){if(!(s<e)||typeof t!=='string')throw p}}}"
              "console.log('node ok',Object.keys(S).map(l=>l+':'+Object.keys(S[l]).length).join(' '))")
        try:
            print(subprocess.check_output(['node', '-e', js, out], text=True).strip())
        except FileNotFoundError:
            print('node not available, skipped JS load check')
    print('OK')


if __name__ == '__main__':
    main()
