# Đọc thử vài câu trong app bằng các giọng VOICEVOX (engine chạy ở localhost:50021).
import json, subprocess, urllib.request, urllib.parse, os, sys
E = 'http://127.0.0.1:50021'
WANT = [('四国めたん','ノーマル'),('春日部つむぎ','ノーマル'),('冥鳴ひまり','ノーマル'),('No.7','アナウンス'),
        ('青山龍星','ノーマル'),('玄野武宏','ノーマル'),('剣崎雌雄','ノーマル'),('雀松朱司','ノーマル')]
LINES = ['勉強','毎朝、駅まで歩いて行きます。','すみません、保険証を忘れてしまったんですが、どうすればいいですか。',
         '恐れ入りますが、少々お待ちいただけますでしょうか。',
         '地震が起きたときは、まず机の下に入って、頭を守ってください。',
         '近年、在宅勤務が広がったことで、都市と地方の関係も少しずつ変わりつつある。']
def get(u): return json.load(urllib.request.urlopen(E+u))
def post(u, data=None, js=None):
    req = urllib.request.Request(E+u, data=(json.dumps(js).encode() if js is not None else data or b''), method='POST',
                                 headers={'Content-Type':'application/json'})
    return urllib.request.urlopen(req).read()
os.makedirs('out', exist_ok=True)
sp = get('/speakers'); json.dump(sp, open('out/speakers.json','w'), ensure_ascii=False, indent=1)
os.makedirs('out', exist_ok=True); made = []
for name, style in WANT:
    s = next((x for x in sp if x['name'] == name), None)
    st = s and next((y for y in s['styles'] if y['name'] == style), None)
    if not st: print('missing', name, style); continue
    try: post('/initialize_speaker?speaker=%d' % st['id'])
    except Exception: pass
    parts = []
    for i, t in enumerate(LINES):
        q = json.loads(post('/audio_query?' + urllib.parse.urlencode({'text': t, 'speaker': st['id']})))
        q['speedScale'] = 1.0; q['postPhonemeLength'] = 0.6
        w = post('/synthesis?speaker=%d' % st['id'], js=q)
        f = 'out/p_%d_%d.wav' % (st['id'], i); open(f, 'wb').write(w); parts.append(f)
    lst = 'out/l_%d.txt' % st['id']; open(lst, 'w').write(''.join("file '%s'\n" % os.path.basename(p) for p in parts))
    mp3 = 'out/%02d_%s_%s.mp3' % (len(made)+1, name.replace('.', ''), style)
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', lst, '-ac', '1', '-b:a', '64k', mp3], check=True)
    made.append(mp3); print('ok', mp3)
print(len(made), 'voices')
