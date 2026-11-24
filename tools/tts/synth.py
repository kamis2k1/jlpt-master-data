#!/usr/bin/env python3
"""Synthesise one chunk of tools/tts/sentences/<LV>.json with one VOICEVOX voice -> Ogg Opus clips.

usage: synth.py SENTENCES.json VOICE_ID CHUNK NCHUNKS OUT_DIR [ENGINE_URL,ENGINE_URL,...]
  writes OUT_DIR/<key>.ogg for every key of the chunk (aliases sharing one text get a copy of the same clip)
  and OUT_DIR/_chunk<CHUNK>.json = {"ok": n, "skipped": [[key, text, error], ...], "sec": seconds}
  usage: synth.py --chunks SENTENCES.json NCHUNKS   -> prints the clip count of every chunk (no engine needed)

Text: t may contain furigana markup {漢字|かな}. The kanji text is sent to VOICEVOX first (natural accents);
if the reading of a marked word does not appear (in order) in the moras VOICEVOX produced, that word is
replaced by its kana and the query is made again.
Audio: speedScale 1.0, pre/post phoneme length 0.1 s, 24 kHz mono -> libopus 24 kbps (ffmpeg).
"""
import concurrent.futures as cf
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from textkey import norm  # noqa: E402

VOICES = {  # voiceId -> (VOICEVOX speaker name, style)  (VOICE-CONTRACT.md)
    'f2': ('春日部つむぎ', 'ノーマル'),
    'f3': ('冥鳴ひまり', 'ノーマル'),
    'f4': ('No.7', 'アナウンス'),
    'm5': ('青山龍星', 'ノーマル'),
    'm7': ('剣崎雌雄', 'ノーマル'),
    'm8': ('雀松朱司', 'ノーマル'),
}
RB = re.compile(r'\{([^|{}]+)\|([^{}]+)\}')


def groups(path):
    """unique synthesis texts in file order -> [(t, [keys])]"""
    order, by = [], {}
    for x in json.load(open(path, encoding='utf-8')):
        if x['t'] not in by:
            by[x['t']] = []
            order.append(x['t'])
        by[x['t']].append(x['k'])
    return [(t, by[t]) for t in order]


def chunk(gs, i, n):
    """contiguous split of the groups into n parts of about equal text length"""
    w = [len(norm(RB.sub(r'\2', t))) + 12 for t, _ in gs]
    tot = sum(w)
    out, acc = [], 0
    for g, x in zip(gs, w):
        mid = acc + x / 2
        if min(n - 1, int(mid * n / tot)) == i:
            out.append(g)
        acc += x
    return out


class Engine:
    def __init__(self, url):
        self.url = url.rstrip('/')

    def req(self, path, js=None, raw=False, tries=4):
        last = None
        for a in range(tries):
            try:
                data = json.dumps(js).encode() if js is not None else (b'' if path.startswith(('/audio_query', '/initialize')) else None)
                r = urllib.request.Request(self.url + path, data=data, method='POST' if data is not None else 'GET',
                                           headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(r, timeout=600) as f:
                    b = f.read()
                return b if raw else json.loads(b)
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(2 + 3 * a)
        raise last

    def query(self, text, sid):
        return self.req('/audio_query?' + urllib.parse.urlencode({'text': text, 'speaker': sid}))

    def synth(self, q, sid):
        return self.req('/synthesis?speaker=%d' % sid, js=q, raw=True)


def kana_norm(s):
    s = ''.join(chr(ord(c) - 0x60) if 'ァ' <= c <= 'ヶ' else c for c in s)
    s = s.translate(str.maketrans('ぢづをわゎへ', 'じずおははえ'))
    return re.sub('[あいうえおー]', 'V', s)


def moras(q):
    return kana_norm(''.join(m['text'] for ap in q.get('accent_phrases', []) for m in ap['moras']))


def resolve(eng, t, sid):
    """-> (audio_query, text used)"""
    units = list(RB.finditer(t))
    base = RB.sub(r'\1', t)
    q = eng.query(base, sid)
    if not units:
        return q, base
    act, pos, miss = moras(q), 0, set()
    for m in units:
        r = kana_norm(re.sub(r'[^ぁ-ゖァ-ヺー]', '', m.group(2)))
        if not r:
            continue
        j = act.find(r, pos)
        if j < 0:
            miss.add(m.start())
        else:
            pos = j + len(r)
    if not miss:
        return q, base
    txt = RB.sub(lambda m: m.group(2) if m.start() in miss else m.group(1), t)
    return eng.query(txt, sid), txt


def to_ogg(wav, out):
    subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-y', '-f', 'wav', '-i', 'pipe:0', '-ac', '1', '-ar', '24000',
                    '-c:a', 'libopus', '-b:a', '24k', '-vbr', 'on', '-application', 'voip', '-map_metadata', '-1', out],
                   input=wav, check=True)


def speaker_id(eng, vid):
    name, style = VOICES[vid]
    for s in eng.req('/speakers'):
        if s['name'] == name:
            for st in s['styles']:
                if st['name'] == style:
                    return st['id']
    sys.exit('voice not found in engine: %s %s / %s' % (vid, name, style))


def main(a):
    if a and a[0] == '--chunks':
        gs = groups(a[1])
        print(json.dumps([len(chunk(gs, i, int(a[2]))) for i in range(int(a[2]))]))
        return
    src, vid, ci, nc, out = a[0], a[1], int(a[2]), int(a[3]), a[4]
    urls = (a[5] if len(a) > 5 else 'http://127.0.0.1:50021').split(',')
    engines = [Engine(u) for u in urls]
    os.makedirs(out, exist_ok=True)
    sid = speaker_id(engines[0], vid)
    for e in engines:
        try:
            e.req('/initialize_speaker?speaker=%d' % sid, raw=True)
        except Exception:  # noqa: BLE001
            pass
    todo = chunk(groups(src), ci, nc)
    if os.environ.get('SYNTH_LIMIT'):
        todo = todo[:int(os.environ['SYNTH_LIMIT'])]
    print('voice', vid, 'speaker', sid, 'chunk', ci, '/', nc, ':', len(todo), 'clips', flush=True)
    t0 = time.time()
    lock = threading.Lock()
    done = {'n': 0, 'kana': 0}
    skipped = []
    free = list(engines)

    def work(g):
        t, keys = g
        with lock:
            eng = free.pop(0)
        try:
            dst = [os.path.join(out, k + '.ogg') for k in keys]
            if all(os.path.isfile(p) and os.path.getsize(p) > 0 for p in dst):
                return
            q, used = resolve(eng, t, sid)
            if used != RB.sub(r'\1', t):
                with lock:
                    done['kana'] += 1
                    if done['kana'] <= 5:
                        print('kana:', used[:80], flush=True)
            q.update(speedScale=1.0, prePhonemeLength=0.1, postPhonemeLength=0.1, outputSamplingRate=24000,
                     outputStereo=False)
            wav = eng.synth(q, sid)
            fd, tmp = tempfile.mkstemp(prefix='_tmp', suffix='.ogg', dir=out)
            os.close(fd)
            to_ogg(wav, tmp)
            for p in dst[1:]:
                shutil.copyfile(tmp, p)
            os.replace(tmp, dst[0])
        except Exception as e:  # noqa: BLE001
            with lock:
                skipped.extend([k, t, str(e)[:200]] for k in keys)
        finally:
            with lock:
                free.append(eng)
                done['n'] += 1
                n = done['n']
            if n % 100 == 0 or n == len(todo):
                el = time.time() - t0
                print('%d/%d  %.0fs  %.2fs/clip' % (n, len(todo), el, el / n), flush=True)

    with cf.ThreadPoolExecutor(len(engines)) as ex:
        list(ex.map(work, todo))
    sec = round(time.time() - t0)
    ok = sum(len(k) for _, k in todo) - len(skipped)
    json.dump({'ok': ok, 'skipped': skipped, 'sec': sec, 'voice': vid, 'chunk': ci, 'kana': done['kana']},
              open(os.path.join(out, '_chunk%d.json' % ci), 'w', encoding='utf-8'), ensure_ascii=False)
    print('done', ok, 'files,', len(skipped), 'skipped,', sec, 's,', done['kana'], 'clips with kana substitution')
    for s in skipped[:20]:
        print('SKIP', s)


if __name__ == '__main__':
    main(sys.argv[1:])
