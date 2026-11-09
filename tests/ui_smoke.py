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
        b = await p.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--use-gl=swiftshader', '--enable-unsafe-swiftshader'])
        ctx = await b.new_context(viewport={'width':390, 'height':844}, geolocation={'latitude':35.7495, 'longitude':139.8040, 'accuracy':8}, permissions=['geolocation'])
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

        print('2. 検索 → ルート → 回避')
        await ctx.set_geolocation({'latitude':35.7580, 'longitude':139.8160, 'accuracy':8}); await pg.wait_for_timeout(1500)
        await pg.fill('#q2', '江北橋'); await pg.press('#q2', 'Enter'); await pg.wait_for_timeout(3500)
        ok(await pg.locator('#searchPanel .res').count() > 0, '検索結果が出る')
        await pg.locator('#searchPanel .res').first.click()
        for i in range(30):
            await pg.wait_for_timeout(800)
            if (await st())['state'] == 'preview': break
        ok((await st())['state'] == 'preview' and await pg.is_visible('#btnStart'), 'ルート確認画面と「開始」ボタンが出る')
        chip = pg.locator('#pvAvoid [data-avoid]')
        if await chip.count():
            name = await chip.first.get_attribute('data-avoid')
            await chip.first.click()
            for i in range(30):
                await pg.wait_for_timeout(800)
                if '避け中' in await pg.inner_text('#pvAvoid'): break
            await pg.wait_for_timeout(1000)
            ok(name not in (await pg.inner_text('#pvInfo')).split('\n')[0], f'「{name}を避ける」で、その道路を使わないルートになる')
            await pg.locator('#pvAvoid [data-unavoid]').first.click(); await pg.wait_for_timeout(5000)
        else:
            print('  - 回避できる高速道路がルートに無いため省略')

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

        print('4. メモと走行記録')
        await pg.click('#btnMemo'); await pg.wait_for_timeout(400)
        ok(await pg.is_visible('#memoBox'), 'メモ画面が開く')
        await pg.fill('#memoText', '自動テストのメモ'); await pg.click('#btnMemoSave'); await pg.wait_for_timeout(300)
        await pg.click('#navEnd'); await pg.wait_for_timeout(800)
        rides = await pg.evaluate("() => JSON.parse(localStorage.getItem('rides')||'[]')")
        ok(rides and len(rides[-1]['fixes']) > 5 and any(e['type'] == 'memo' for e in rides[-1]['events']), '走行記録とメモが保存される')
        played = [e for r in rides for e in r['events'] if e['type'] == 'speak' and e.get('played')]
        ok(not played, '「鳴らさない」設定（初期値）では音を出さない')

        ok(not errs, 'ページのエラーがない' + ('' if not errs else '：' + errs[0][:120]))
        await b.close()
    srv.shutdown()
    print('NG（%d件）' % len(fails) if fails else 'OK：画面操作テスト')
    sys.exit(1 if fails else 0)

asyncio.run(main())
