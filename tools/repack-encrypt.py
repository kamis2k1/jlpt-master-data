#!/usr/bin/env python3
"""Re-pack a plaintext study-material pack (zip) into the encrypted pack format.

Encrypted pack format (must match www/index.html encId(), android EncStore.java, desktop/enc.js):
  * every file of the source zip becomes ONE zip entry  jm/<id>  (stored, no compression)
  * id  = first 32 hex chars of SHA-256( SALT + "\n" + NFC(relative path) )
          relative path = the zip entry name, e.g. "N3_full/2. CHẶNG 2 (...)/a.mp3"
          (= the path used in the app data without the leading "../")
  * data = AES-256-CTR(KEY, IV, plaintext), same length as the plaintext
  * IV  = first 16 bytes of SHA-256( "iv:" + id ), the 128-bit counter starts there (big endian)
The original file names never appear in the output zip.

KEY (64 hex chars) and SALT (32 hex chars) come from the environment variables N1_ENC_KEY / N1_ENC_SALT
(GitHub secrets in the data repo workflow). They must be the same values that are built into the app.

Usage:
  repack-encrypt.py encrypt IN.zip OUT.zip            -> prints {"sha256","size","files"} as JSON
  repack-encrypt.py packs OLD_packs.json DIR BASE_URL VER OUT_packs.json
        builds a packs.json for the encrypted zips in DIR (same names as in OLD_packs.json),
        url = BASE_URL/<name>, ver = VER, enc = 1
  repack-encrypt.py id "N3_full/x/y.mp3"             -> prints the id (for checks)
  repack-encrypt.py decrypt IN_enc.zip OUT_DIR "relative/path" ...   -> restores files (admin/testing)

Requires: pip install cryptography
"""
import hashlib
import json
import os
import sys
import unicodedata
import zipfile

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

CHUNK = 1 << 20


def env_hex(name, nbytes):
    v = os.environ.get(name, '').strip().lower()
    if len(v) != nbytes * 2 or any(c not in '0123456789abcdef' for c in v):
        sys.exit(f'{name} must be {nbytes * 2} hex characters')
    return v


def key():
    return bytes.fromhex(env_hex('N1_ENC_KEY', 32))


def salt():
    return env_hex('N1_ENC_SALT', 16)


def enc_id(rel, s=None):
    rel = unicodedata.normalize('NFC', rel.replace('\\', '/'))
    return hashlib.sha256(((s or salt()) + '\n' + rel).encode('utf-8')).hexdigest()[:32]


def enc_iv(i):
    return hashlib.sha256(('iv:' + i).encode('ascii')).digest()[:16]


def cipher(k, i, offset=0):
    """AES-256-CTR positioned at byte `offset` of file `i` (same arithmetic as the app servers)."""
    ctr = (int.from_bytes(enc_iv(i), 'big') + offset // 16) % (1 << 128)
    c = Cipher(algorithms.AES(k), modes.CTR(ctr.to_bytes(16, 'big'))).encryptor()
    if offset % 16:
        c.update(b'\0' * (offset % 16))
    return c


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(CHUNK), b''):
            h.update(b)
    return h.hexdigest()


def cmd_encrypt(src, dst):
    k, s = key(), salt()
    seen = {}
    n = 0
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst + '.part', 'w', zipfile.ZIP_STORED, allowZip64=True) as zout:
        for info in zin.infolist():
            if info.is_dir():
                continue
            i = enc_id(info.filename, s)
            if i in seen:
                sys.exit(f'id collision: {info.filename} / {seen[i]}')
            seen[i] = info.filename
            zi = zipfile.ZipInfo('jm/' + i, date_time=(2024, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_STORED
            zi.file_size = info.file_size
            zi.external_attr = 0o644 << 16
            c = cipher(k, i)
            with zin.open(info) as fi, zout.open(zi, 'w', force_zip64=info.file_size > 0x7fffffff) as fo:
                for b in iter(lambda: fi.read(CHUNK), b''):
                    fo.write(c.update(b))
                fo.write(c.finalize())
            n += 1
    os.replace(dst + '.part', dst)
    out = {'sha256': sha256_file(dst), 'size': os.path.getsize(dst), 'files': n}
    print(json.dumps(out))
    return out


def cmd_packs(old_json, d, base_url, ver, out_json):
    old = json.load(open(old_json, encoding='utf-8'))
    packs = []
    for p in old['packs']:
        z = os.path.join(d, p['name'])
        if not os.path.isfile(z):
            sys.exit('missing encrypted zip: ' + z)
        with zipfile.ZipFile(z) as zf:
            files = sum(1 for x in zf.infolist() if not x.is_dir())
        q = dict(p)
        q.update(url=base_url.rstrip('/') + '/' + p['name'], ver=ver, sha256=sha256_file(z),
                 size=os.path.getsize(z), files=files, enc=1)
        packs.append(q)
    json.dump({'version': ver, 'enc': 1, 'packs': packs}, open(out_json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('wrote', out_json, len(packs), 'packs')


def cmd_decrypt(src, outdir, rels):
    k, s = key(), salt()
    with zipfile.ZipFile(src) as zf:
        for rel in rels:
            i = enc_id(rel, s)
            c = cipher(k, i)
            out = os.path.join(outdir, os.path.basename(rel))
            with zf.open('jm/' + i) as fi, open(out, 'wb') as fo:
                for b in iter(lambda: fi.read(CHUNK), b''):
                    fo.write(c.update(b))
            print(out)


def main(a):
    if len(a) == 3 and a[0] == 'encrypt':
        cmd_encrypt(a[1], a[2])
    elif len(a) == 6 and a[0] == 'packs':
        cmd_packs(*a[1:])
    elif len(a) == 2 and a[0] == 'id':
        print(enc_id(a[1]))
    elif len(a) >= 4 and a[0] == 'decrypt':
        cmd_decrypt(a[1], a[2], a[3:])
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
