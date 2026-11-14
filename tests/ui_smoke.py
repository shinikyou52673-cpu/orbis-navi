#!/usr/bin/env python3
"""画面操作の自動テスト（ヘッドレスChrome・iPhoneサイズ・GPSを動かして確認）。
プログラム（画面・判定・ルート）を変えたら必ず実行し、すべて OK のときだけ反映すること。
実行: python3 tests/ui_smoke.py   （リポジトリのルートで。地図・ルート検索の公開サーバーを使うため数分かかる）
"""
import asyncio, http.server, json, math, os, socketserver, sys, threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = []
def ok(cond, msg):
    print(('  ✓ ' if cond else '  ✗ ') + msg)
    if not cond: fails.append(msg)
def mv(lat, lon, d, brg):
    r = math.radians(brg); return lat + d*math.cos(r)/110540, lon + d*math.sin(r)/(111320*math.cos(math.radians(lat)))

def serve():
    class Q(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k): super().__init__(*a, directory=ROOT, **k)
        def log_message(self, *a): pass
    srv = socketserver.TCPServer(('127.0.0.1', 0), Q); threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv

async def main():
    from playwright.async_api import async_playwright
    srv = serve(); url = f'http://127.0.0.1:{srv.server_address[1]}/index.html'
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--use-gl=swiftshader', '--enable-unsafe-swiftshader', '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'])
        ctx = await b.new_context(viewport={'width':390, 'height':844}, geolocation={'latitude':35.7495, 'longitude':139.8040, 'accuracy':8}, permissions=['geolocation', 'microphone'])
        # 音声認識の代わり（__say('…') で「話した」ことにする）
        await ctx.add_init_script('''(() => { window.__srs = [];
          class FakeSR { constructor(){ window.__srs.push(this); } start(){ this.started = true; setTimeout(() => this.onstart && this.onstart(), 5); }
            stop(){ this._end(); } abort(){ this._end(); } _end(){ if (this.ended) return; this.ended = true; setTimeout(() => this.onend && this.onend(), 5); } }
          window.SpeechRecognition = FakeSR; window.webkitSpeechRecognition = FakeSR;
          window.__say = t => { const r = [...window.__srs].reverse().find(x => x.started && !x.ended); if (!r) return false;
            const res = [{ transcript:t }]; res.isFinal = true; r.onresult && r.onresult({ resultIndex:0, results:[res] }); r._end(); return true; };
        })()''')
        pg = await ctx.new_page(); errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        await pg.goto(url); await pg.wait_for_timeout(3000)
        st = lambda: pg.evaluate("() => ({state: __orbisNavi.getState(), follow: __orbisNavi.cam.follow, bearing: __orbisNavi.map.getBearing()})")

        print('1. 待機中の追従')
        lat, lon = 35.7495, 139.8040
        for i in range(8):
            lat, lon = mv(lat, lon, 15, 45); await ctx.set_geolocation({'latitude':lat, 'longitude':lon, 'accuracy':8}); await pg.wait_for_timeout(900)
        s = await st(); ok(s['follow'] and abs(((s['bearing'] - 45 + 540) % 360) - 180) < 25, f"北東へ走ると進行方向が上になる（bearing {s['bearing']:.0f}）")
        await pg.mouse.move(195, 450); await pg.mouse.down(); await pg.mouse.move(80, 300, steps=8); await pg.mouse.up(); await pg.wait_for_timeout(400)
        ok(not (await st())['follow'], 'ドラッグで追従が外れる')
        await pg.click('#btnLocate'); await pg.wait_for_timeout(1000)
        ok((await st())['follow'], '現在地ボタンで追従に戻る')

        async def search(q):
            await pg.fill('#q2', q); await pg.press('#q2', 'Enter')
            for i in range(20):
                await pg.wait_for_timeout(600)
                if await pg.locator('#searchPanel .res').count() or '見つかりません' in await pg.inner_text('#searchPanel') or '失敗' in await pg.inner_text('#searchPanel'): break
        async def wait_preview():
            for i in range(40):
                await pg.wait_for_timeout(800)
                if (await st())['state'] == 'preview': break

        print('2a. 住所の検索、有料と下道の候補、路線の回避（上野→羽田空港）')
        await ctx.set_geolocation({'latitude':35.7138, 'longitude':139.7773, 'accuracy':8}); await pg.wait_for_timeout(1500)
        await search('墨田区石原1-1')
        ok(await pg.locator('#searchPanel .res').count() > 0 and '石原' in await pg.locator('#searchPanel .res').first.inner_text(), '番地までの住所で検索できる')
        await search('羽田空港第1ターミナル')
        ok(await pg.locator('#searchPanel .res').count() > 0, '施設名で検索できる')
        await pg.locator('#searchPanel .res').first.click(); await wait_preview()
        ok((await st())['state'] == 'preview', '長い区間のルート確認画面が出る')
        chips = ''
        for i in range(25):
            chips = await pg.inner_text('#pvChips')
            if ('下道' in chips or '無料' in chips) and '検索中' not in chips: break
            await pg.wait_for_timeout(800)
        ok('円' in chips and ('下道' in chips or '無料' in chips) and '検索中' not in chips, '有料道路を使うルートと、下道のルートの両方が候補に出る：' + chips.replace('\n', ' ')[:70])
        ok('首都高 約' in await pg.inner_text('#pvInfo'), '首都高を使うルートでは料金の概算が出る')
        kinds = await pg.evaluate("() => __orbisNavi.getRoutes().map(r => [r.kind, r.hasToll, Math.round(r.time/60), Math.round(r.length/100)/10])")
        ok(any(k[0] == 'free' and not k[1] for k in kinds), f'下道の候補は有料道路を通らない：{kinds}')
        chip = pg.locator('#pvAvoid [data-avoid]')
        ok(await chip.count() > 0, '高速道路を使うルートには「○○を避ける」が出る')
        if await chip.count():
            name = await chip.first.get_attribute('data-avoid')
            await chip.first.click()
            for i in range(30):
                await pg.wait_for_timeout(800)
                if '避け中' in await pg.inner_text('#pvAvoid'): break
            await pg.wait_for_timeout(1500)
            ok(name not in (await pg.inner_text('#pvInfo')).split('\n')[0], f'「{name}を避ける」で、その道路を使わないルートになる')
            await pg.locator('#pvAvoid [data-unavoid]').first.click(); await pg.wait_for_timeout(6000)
        await pg.click('#btnPvClose'); await pg.wait_for_timeout(600)

        print('2b. 検索 → ルート確認（近い区間）')
        await ctx.set_geolocation({'latitude':35.7580, 'longitude':139.8160, 'accuracy':8}); await pg.wait_for_timeout(1500)
        await search('江北橋')
        ok(await pg.locator('#searchPanel .res').count() > 0, '検索結果が出る')
        await pg.locator('#searchPanel .res').first.click(); await wait_preview()
        ok((await st())['state'] == 'preview' and await pg.is_visible('#btnStart'), 'ルート確認画面と「開始」ボタンが出る')
        await pg.wait_for_timeout(4000)   # 下道の追加検索が終わるのを待つ

        print('3. 案内 → 逆走 → 再検索')
        await pg.click('#btnStart'); await pg.wait_for_timeout(800)
        ok((await st())['state'] == 'nav', '「開始」で案内が始まる')
        coords = await pg.evaluate("() => __orbisNavi.getRoutes()[0].coords.map(c=>[c.lat,c.lon])")
        cum = [0]
        for i in range(1, len(coords)):
            a, c = coords[i-1], coords[i]; cum.append(cum[-1] + math.hypot((c[0]-a[0])*110540, (c[1]-a[1])*90000))
        def at(sv):
            for i in range(1, len(cum)):
                if cum[i] >= sv:
                    t = (sv - cum[i-1]) / max(cum[i] - cum[i-1], 1e-6); return coords[i-1][0] + (coords[i][0]-coords[i-1][0])*t, coords[i-1][1] + (coords[i][1]-coords[i-1][1])*t
            return coords[-1]
        sv = 0
        for i in range(25):
            sv += 12; la, lo = at(sv); await ctx.set_geolocation({'latitude':la, 'longitude':lo, 'accuracy':8}); await pg.wait_for_timeout(600)
        ok(await pg.inner_text('#modeChip') == 'ルート上', 'ルートに沿って走ると「ルート上」')
        seen_ww = False
        for i in range(25):
            sv -= 12; la, lo = at(max(sv, 0)); await ctx.set_geolocation({'latitude':la, 'longitude':lo, 'accuracy':8}); await pg.wait_for_timeout(600)
            if '逆方向' in await pg.inner_text('#navStatus'): seen_ww = True
        ok(seen_ww, '引き返すと「逆方向に進んでいます」になる')
        ev = []
        for i in range(15):
            await pg.wait_for_timeout(1000)
            ev = await pg.evaluate("() => __orbisNavi.getRide().events.filter(e=>e.type==='reroute')")
            if ev: break
        ok(bool(ev) and ev[-1].get('ok'), '逆走から自動で再検索される')
        ok(bool(ev) and not ev[-1].get('uturn'), '再検索したルートがUターンから始まらない')
        await pg.mouse.move(195, 500); await pg.mouse.down(); await pg.mouse.move(300, 350, steps=8); await pg.mouse.up(); await pg.wait_for_timeout(400)
        ok(await pg.is_visible('#btnRecenter'), '案内中に地図を動かすと「再センター」が出る')
        await pg.click('#btnRecenter'); await pg.wait_for_timeout(600)
        ok((await st())['follow'], '「再センター」で追従に戻る')

        print('4. 声でメモ（手袋のまま）')
        await pg.evaluate("() => { const o = document.getElementById('optVoice'); o.value = 'quiet'; o.dispatchEvent(new Event('change')); }")
        await pg.wait_for_timeout(500)
        ok(await pg.evaluate("() => __orbisNavi.voice.want"), '「声で操作」を選ぶと聞き取りが始まる')
        async def say(t):
            for i in range(20):
                if await pg.evaluate("t => __say(t)", t): break
                await pg.wait_for_timeout(150)
            await pg.wait_for_timeout(400)
        await say('メモ開始')
        ok(await pg.is_visible('#vmBanner'), '「メモ開始」で録音中の表示が出る')
        await say('ここの案内が遅い')
        ok('ここの案内が遅い' in await pg.inner_text('#vmText'), '話した内容が録音中の表示に出る')
        await say('メモ終了')
        memos = await pg.evaluate("() => JSON.parse(localStorage.getItem('memos')||'[]')")
        ok(not await pg.is_visible('#vmBanner') and memos and memos[-1]['text'] == 'ここの案内が遅い' and memos[-1].get('via') == 'voice', '「メモ終了」で声のメモが保存される')
        await say('メモ開始'); await say('取り消すメモ'); await say('メモ取り消し')
        memos2 = await pg.evaluate("() => JSON.parse(localStorage.getItem('memos')||'[]')")
        ok(len(memos2) == len(memos), '「メモ取り消し」では保存しない')
        await say('今日は寒い')
        ok(await pg.evaluate("() => __orbisNavi.voice.want && !__orbisNavi.voice.vm.on"), '普通の会話では録音が始まらず、聞き取りは続く')

        print('5. メモと走行記録')
        await pg.click('#btnMemo'); await pg.wait_for_timeout(400)
        ok(await pg.is_visible('#memoBox'), 'メモ画面が開く')
        await pg.fill('#memoText', '自動テストのメモ'); await pg.click('#btnMemoSave'); await pg.wait_for_timeout(300)
        await pg.click('#navEnd'); await pg.wait_for_timeout(800)
        rides = await pg.evaluate("() => JSON.parse(localStorage.getItem('rides')||'[]')")
        ok(rides and len(rides[-1]['fixes']) > 5 and any(e['type'] == 'memo' for e in rides[-1]['events']), '走行記録とメモが保存される')
        played = [e for r in rides for e in r['events'] if e['type'] == 'speak' and e.get('played')]
        ok(not played, '「鳴らさない」設定（初期値）では音を出さない')
        ok(not await pg.evaluate("() => __orbisNavi.voice.want"), '案内を終えると声の聞き取りも止まる')
        ok(any(e['type'] == 'memo' and e.get('via') == 'voice' for e in rides[-1]['events']), '声のメモも走行記録に残る')

        print('6. 二輪通行禁止の表示（模擬データ）')
        n = await pg.evaluate("""() => __orbisNavi.motoTest({elements:[{type:'way',id:1,tags:{highway:'residential',name:'テスト通り',motorcycle:'no'},geometry:[{lat:35.75,lon:139.80},{lat:35.751,lon:139.801}]},
          {type:'way',id:2,tags:{highway:'tertiary','motorcycle:conditional':'no @ (22:00-06:00)'},geometry:[{lat:35.752,lon:139.80},{lat:35.753,lon:139.801}]}]})""")
        ok(n == 2 and await pg.evaluate("() => !!__orbisNavi.map.getLayer('moto-no')"), '規制のある道路が地図に描かれる')
        ok(await pg.evaluate("() => !!__orbisNavi.map.getLayer('spd-roads')"), '速度取締りエリアの道路が地図に描かれる')

        print('7. 送れなかった分のやり直し、終了を押さずに閉じた走行記録')
        await pg.click('#btnStart') if await pg.is_visible('#btnStart') else None
        await pg.wait_for_timeout(500)
        if (await st())['state'] != 'nav':
            await pg.evaluate("() => document.getElementById('btnFree').click()"); await pg.wait_for_timeout(800)
        for i in range(4):
            la, lo = at(12 * i); await ctx.set_geolocation({'latitude':la, 'longitude':lo, 'accuracy':8}); await pg.wait_for_timeout(700)
        await pg.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))")   # 控えを取らせる（hidden 扱いでなくても30秒ごとに取る）
        await pg.evaluate("() => window.dispatchEvent(new Event('pagehide'))")
        cur = await pg.evaluate("() => JSON.parse(localStorage.getItem('rideCur')||'null')")
        ok(bool(cur) and len(cur['fixes']) > 0, '案内中の走行記録が端末に控えられる')
        await pg.evaluate("() => { const m = JSON.parse(localStorage.getItem('memos')||'[]'); m.forEach(x => x.uploaded = false); localStorage.setItem('memos', JSON.stringify(m)); }")
        link = await pg.evaluate("() => { document.getElementById('fbRepo').value = 'test/feedback'; document.getElementById('fbToken').value = 'dummy'; let got = null; navigator.clipboard.writeText = async t => { got = t; }; document.getElementById('btnFbLink').click(); return new Promise(r => setTimeout(() => r(got), 300)); }")
        ok(bool(link) and '#fb=' in link, '送信設定を移すリンクを作れる')
        await pg.evaluate("() => localStorage.removeItem('fbCfg')")
        puts = []; state_ = {'n': 0}
        async def gh(route):
            state_['n'] += 1; puts.append(route.request.url.split('/contents/')[-1])
            if state_['n'] == 1: await route.abort()                  # 1回目は電波が無い
            elif state_['n'] == 2: await route.fulfill(status=422, body='{}')   # 2回目は「もうある」
            else: await route.fulfill(status=201, body='{}')
        await ctx.route('https://api.github.com/**', gh)
        await pg.goto(url + '?t=1' + link[link.index('#fb='):]); await pg.wait_for_timeout(6000)   # 別のブラウザでリンクを開いた想定（タブを閉じて開き直したのと同じ）
        cfg = await pg.evaluate("() => [JSON.parse(localStorage.getItem('fbCfg')||'{}'), location.hash]")
        ok(cfg[0].get('repo') == 'test/feedback' and cfg[0].get('token') == 'dummy' and cfg[1] == '', 'リンクを開くと送信設定が入り、リンクの印は消える')
        rides = await pg.evaluate("() => JSON.parse(localStorage.getItem('rides')||'[]')")
        ok(any(r['id'] == cur['id'] and r['events'][-1].get('reason') == 'interrupted' for r in rides), '終了を押さずに閉じた回の走行記録が、次に開いたとき保存される')
        ok(not await pg.evaluate("() => localStorage.getItem('rideCur')"), '控えは保存後に消える')
        await pg.evaluate("() => window.dispatchEvent(new Event('online'))"); await pg.wait_for_timeout(3000)
        left = await pg.evaluate("() => ['memos','rides'].reduce((c,k)=>c+JSON.parse(localStorage.getItem(k)||'[]').filter(r=>!r.uploaded).length,0)")
        ok(left == 0 and any(u.startswith('memos/') for u in puts) and any(u.startswith('rides/') for u in puts), f'送信に失敗しても、電波が戻るとやり直して全部送る（送信{len(puts)}回）')
        ok('未送信はありません' in await pg.inner_text('#fbStatus'), '設定に「未送信はありません」と出る')

        print('8. マイクと音声認識のテスト')
        await pg.evaluate("() => document.getElementById('btnMicTest').click()")
        for i in range(30):
            await pg.wait_for_timeout(700)
            if '音声認識：' in await pg.inner_text('#micTestOut'): break
        txt = await pg.inner_text('#micTestOut')
        ok('マイク：' in txt and '音声認識：' in txt, 'テスト結果（マイク・音声認識）が表示される：' + txt.replace('\n', ' ')[:80])
        dg = await pg.evaluate("() => JSON.parse(localStorage.getItem('diags')||'[]')")
        ok(dg and dg[-1]['gum'] == 'ok' and dg[-1]['srEvents'], 'テスト結果が端末に残る')
        await pg.wait_for_timeout(1500)
        ok(any(u.startswith('diag/') for u in puts), 'テスト結果を送信先に送る')

        ok(not errs, 'ページのエラーがない' + ('' if not errs else '：' + errs[0][:120]))
        await b.close()
    srv.shutdown()
    print('NG（%d件）' % len(fails) if fails else 'OK：画面操作テスト')
    sys.exit(1 if fails else 0)

asyncio.run(main())
