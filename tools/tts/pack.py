#!/usr/bin/env python3
"""Voice packs (VOICE-CONTRACT.md): plaintext zip -> encrypted with tools/repack-encrypt.py -> self check.

  pack.py build VOICE LV SENTENCES.json CLIP_DIR OUT_plain.zip
        entries voice/<VOICE>/<key>.ogg for every key of SENTENCES.json found in CLIP_DIR (<key>.ogg),
        plus the index voice/<VOICE>/<LV>.json = JSON array of the keys present.
        prints {"count", "missing", "bytes"} (bytes = total audio bytes)
  pack.py check ENC.zip VOICE LV N
        decrypts the index and N random clips (needs N1_ENC_KEY / N1_ENC_SALT) and runs ffprobe on every clip.
"""
import importlib.util
import json
import os
import random
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('repack', os.path.join(HERE, '..', 'repack-encrypt.py'))
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)


def build(vid, lv, src, clips, out):
    keys, seen = [], set()
    for x in json.load(open(src, encoding='utf-8')):
        if x['k'] not in seen:
            seen.add(x['k'])
            keys.append(x['k'])
    have, missing, total = [], [], 0
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_STORED, allowZip64=True) as z:
        for k in keys:
            p = os.path.join(clips, k + '.ogg')
            if os.path.isfile(p) and os.path.getsize(p) > 0:
                z.write(p, 'voice/%s/%s.ogg' % (vid, k))
                have.append(k)
                total += os.path.getsize(p)
            else:
                missing.append(k)
        z.writestr('voice/%s/%s.json' % (vid, lv), json.dumps(have, separators=(',', ':')))
    print(json.dumps({'count': len(have), 'missing': len(missing), 'bytes': total}))
    if missing:
        print('missing keys:', ' '.join(missing[:50]), file=sys.stderr)
    if len(missing) > 0.02 * len(keys) and not os.environ.get('SYNTH_LIMIT'):
        sys.exit('too many missing clips: %d of %d' % (len(missing), len(keys)))


def read_enc(zf, rel, k, s):
    i = R.enc_id(rel, s)
    c = R.cipher(k, i)
    return c.update(zf.read('jm/' + i)) + c.finalize()


def check(src, vid, lv, n):
    k, s = R.key(), R.salt()
    with zipfile.ZipFile(src) as zf:
        idx = json.loads(read_enc(zf, 'voice/%s/%s.json' % (vid, lv), k, s).decode('utf-8'))
        assert isinstance(idx, list) and idx, 'empty index'
        names = set(zf.namelist())
        assert len(names) == len(idx) + 1, 'entries %d != index %d + 1' % (len(names), len(idx))
        pick = random.Random(7).sample(idx, min(n, len(idx)))
        with tempfile.TemporaryDirectory() as d:
            for key in pick:
                b = read_enc(zf, 'voice/%s/%s.ogg' % (vid, key), k, s)
                assert b[:4] == b'OggS', 'not ogg: ' + key
                p = os.path.join(d, key + '.ogg')
                open(p, 'wb').write(b)
                r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_name,channels,sample_rate:format=duration',
                                    '-of', 'json', p], capture_output=True, text=True, check=True)
                info = json.loads(r.stdout)
                st = info['streams'][0]
                assert st['codec_name'] == 'opus' and int(st['channels']) == 1, r.stdout
                assert float(info['format']['duration']) > 0.2, r.stdout
    print('check ok: %s index %d keys, %d clips decoded and probed' % (os.path.basename(src), len(idx), len(pick)))


if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) == 6 and a[0] == 'build':
        build(*a[1:])
    elif len(a) == 5 and a[0] == 'check':
        check(a[1], a[2], a[3], int(a[4]))
    else:
        sys.exit(__doc__)
