#!/usr/bin/env python3
"""Transcribe one shard of the JLPT listening items with faster-whisper (word timestamps).

  transcribe.py LEVEL SHARD NSHARDS ITEMS.json PACKS.json OUT_DIR [MODEL]

Downloads the encrypted packs of LEVEL listed in PACKS.json (audio pack first, others only while files
are still missing), decrypts the needed mp3 files with N1_ENC_KEY / N1_ENC_SALT (tools/repack-encrypt.py),
and writes OUT_DIR/<LEVEL>/<sha1(item.path)>.json = {"path", "duration", "words": [[s, e, w], ...]}.
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('repack', os.path.join(HERE, '..', 'repack-encrypt.py'))
repack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repack)
sys.path.insert(0, HERE)
from align import split_sentences  # noqa: E402

KIND_ORDER = {'audio': 0, 'books': 1}


def download(url, dst, sha):
    subprocess.run(['curl', '-fsSL', '--retry', '5', '--retry-delay', '10', '-o', dst, url], check=True)
    if sha and repack.sha256_file(dst) != sha:
        sys.exit('sha256 mismatch for ' + url)


def main(level, shard, nshards, items_json, packs_json, out_dir, model_name='small'):
    shard, nshards = int(shard), int(nshards)
    items = json.load(open(items_json, encoding='utf-8'))[level]
    mine = [it for i, it in enumerate(items) if i % nshards == shard]
    k, s = repack.key(), repack.salt()
    need = {}
    for it in mine:
        rel = it['path'][3:] if it['path'].startswith('../') else it['path']
        need[repack.enc_id(rel, s)] = it
    print(f'{level} shard {shard}/{nshards}: {len(mine)} items', flush=True)

    packs = [p for p in json.load(open(packs_json, encoding='utf-8'))['packs'] if p.get('level') == level]
    packs.sort(key=lambda p: KIND_ORDER.get(p.get('kind'), 9))
    tmp = tempfile.mkdtemp()
    audio = {}  # enc id -> decrypted file
    for p in packs:
        if len(audio) == len(need):
            break
        z = os.path.join(tmp, 'pack.zip')
        t0 = time.time()
        download(p['url'], z, p.get('sha256'))
        with zipfile.ZipFile(z) as zf:
            names = set(zf.namelist())
            hit = [i for i in need if i not in audio and 'jm/' + i in names]
            for i in hit:
                dst = os.path.join(tmp, i + '.mp3')
                c = repack.cipher(k, i)
                with zf.open('jm/' + i) as fi, open(dst, 'wb') as fo:
                    for b in iter(lambda: fi.read(repack.CHUNK), b''):
                        fo.write(c.update(b))
                with open(dst, 'rb') as f:
                    head = f.read(3)
                if not (head == b'ID3' or (head[0] == 0xFF and head[1] & 0xE0 == 0xE0)):
                    print('WARNING: decrypted file does not look like mp3:', need[i]['path'], flush=True)
                audio[i] = dst
        os.remove(z)
        print(f"{p['name']}: {len(hit)} files ({time.time() - t0:.0f}s)", flush=True)
    missing = [need[i]['path'] for i in need if i not in audio]
    for m in missing:
        print('MISSING audio:', m, flush=True)

    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device='cpu', compute_type='int8', cpu_threads=os.cpu_count() or 4)
    od = os.path.join(out_dir, level)
    os.makedirs(od, exist_ok=True)
    total_audio = 0.0
    t_all = time.time()
    for n, (i, f) in enumerate(audio.items()):
        it = need[i]
        t0 = time.time()
        prompt = ''.join(split_sentences(it['script']))[:180]
        segs, info = model.transcribe(f, language='ja', word_timestamps=True, vad_filter=True,
                                      beam_size=5, condition_on_previous_text=False, initial_prompt=prompt)
        words = []
        for sg in segs:
            for w in (sg.words or []):
                words.append([round(w.start, 2), round(w.end, 2), w.word, round(w.probability, 3)])
        out = os.path.join(od, hashlib.sha1(it['path'].encode('utf-8')).hexdigest() + '.json')
        json.dump({'path': it['path'], 'duration': round(info.duration, 2), 'model': model_name, 'words': words},
                  open(out, 'w', encoding='utf-8'), ensure_ascii=False)
        total_audio += info.duration
        print(f'[{n + 1}/{len(audio)}] {info.duration:.0f}s audio in {time.time() - t0:.0f}s, {len(words)} words', flush=True)
        os.remove(f)
    json.dump({'level': level, 'shard': shard, 'items': len(mine), 'transcribed': len(audio), 'missing': missing,
               'audio_sec': round(total_audio), 'wall_sec': round(time.time() - t_all)},
              open(os.path.join(od, f'_shard{shard}.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    if len(sys.argv) not in (7, 8):
        sys.exit(__doc__)
    main(*sys.argv[1:])
