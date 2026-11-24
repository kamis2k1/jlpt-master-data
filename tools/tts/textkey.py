"""Text key for VOICEVOX voice packs (VOICE-CONTRACT.md). Python twin of tools/tts/textkey.js.
norm(t): {漢字|かな} -> 漢字; strip HTML tags; NFC; remove all whitespace (exactly the JavaScript \\s set).
key(t) = first 16 hex chars of SHA-256(UTF-8(norm(t))); '' when norm is empty.
"""
import hashlib
import re
import unicodedata

RB = re.compile(r'\{([^|{}]+)\|([^{}]+)\}')
TAG = re.compile(r'<[^>]*>')
# JavaScript \s: WhiteSpace + LineTerminator
WS = re.compile('[\t\n\v\f\r    -     　﻿]+')


def norm(t):
    s = RB.sub(r'\1', '' if t is None else str(t))
    s = TAG.sub('', s)
    s = unicodedata.normalize('NFC', s)
    return WS.sub('', s)


def key(t):
    n = norm(t)
    return hashlib.sha256(n.encode('utf-8')).hexdigest()[:16] if n else ''


if __name__ == '__main__':
    import json
    import sys
    # stdin: JSON array of strings -> stdout: JSON array of [norm, key]
    print(json.dumps([[norm(s), key(s)] for s in json.load(sys.stdin)], ensure_ascii=False))
