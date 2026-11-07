#!/usr/bin/env python3
"""OpenStreetMap系サービス（Valhalla / Nominatim）を、ヘッドレスChrome経由で呼ぶ小道具。
作業環境から curl では届かないことがあるため、ブラウザの fetch を使う。
サーバー負荷を避けるため、1リクエストごとに1.1秒あける。

使い方:
  python3 tools/osm.py search "大井JCT"                      # 地名・JCT・出入口の検索（Nominatim）
  python3 tools/osm.py locate 35.762 139.7985 [heading]       # 近くの道路（車線の向き・道路名）
  python3 tools/osm.py route body.json > route.json           # Valhalla /route（bodyはValhallaのJSON）
  python3 tools/osm.py shape route.json > shape.json          # route.json の道筋を [[lat,lon],...] に
"""
import asyncio, json, sys, urllib.parse

VALHALLA = 'https://valhalla1.openstreetmap.de'
NOMINATIM = 'https://nominatim.openstreetmap.org/search'

JS_FETCH = """async ([url, body]) => {
  const opt = body ? {method:'POST', headers:{'Content-Type':'application/json'}, body} : {};
  const r = await fetch(url, opt);
  return [r.status, await r.text()];
}"""

async def fetch_all(reqs):
    from playwright.async_api import async_playwright
    out = []
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path='/usr/bin/google-chrome')
        pg = await (await b.new_context(extra_http_headers={'Accept-Language': 'ja'})).new_page()
        await pg.set_content('<html><body>osm</body></html>')
        for i, (url, body) in enumerate(reqs):
            if i: await pg.wait_for_timeout(1100)
            status, text = await pg.evaluate(JS_FETCH, [url, body])
            out.append((status, text))
        await b.close()
    return out

def decode6(s):
    i = lat = lon = 0; out = []
    while i < len(s):
        for k in range(2):
            shift = res = 0
            while True:
                b = ord(s[i]) - 63; i += 1
                res |= (b & 0x1f) << shift; shift += 5
                if b < 0x20: break
            d = ~(res >> 1) if res & 1 else res >> 1
            if k == 0: lat += d
            else: lon += d
        out.append([lat / 1e6, lon / 1e6])
    return out

def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    cmd = sys.argv[1]
    if cmd == 'search':
        q = ' '.join(sys.argv[2:])
        url = NOMINATIM + '?format=jsonv2&limit=8&countrycodes=jp&accept-language=ja&q=' + urllib.parse.quote(q)
        st, txt = asyncio.run(fetch_all([(url, None)]))[0]
        for x in json.loads(txt):
            print(x['lat'][:9], x['lon'][:10], x.get('category'), x.get('type'), x['display_name'][:80])
    elif cmd == 'locate':
        lat, lon = float(sys.argv[2]), float(sys.argv[3])
        loc = {'lat': lat, 'lon': lon, 'radius': 300}
        if len(sys.argv) > 4:
            loc.update(heading=float(sys.argv[4]), heading_tolerance=45)
        body = json.dumps({'locations': [loc], 'costing': 'auto', 'verbose': True})
        st, txt = asyncio.run(fetch_all([(VALHALLA + '/locate', body)]))[0]
        j = json.loads(txt)
        for e in (j[0].get('edges') or [])[:10]:
            names = (e.get('edge_info') or {}).get('names') or []
            cls = ((e.get('edge') or {}).get('classification') or {}).get('classification')
            tun = (e.get('edge') or {}).get('tunnel')
            print(f"{e['correlated_lat']:.6f} {e['correlated_lon']:.6f} 距離{round(e.get('distance',0))}m 向き{round(e.get('heading',-1))}° {cls}{' トンネル' if tun else ''} {'/'.join(names[:3])}")
    elif cmd == 'route':
        body = open(sys.argv[2], encoding='utf-8').read()
        st, txt = asyncio.run(fetch_all([(VALHALLA + '/route', body)]))[0]
        if st != 200: sys.stderr.write(f'HTTP {st}\n')
        print(txt)
    elif cmd == 'shape':
        j = json.load(open(sys.argv[2], encoding='utf-8'))
        pts = []
        for li, leg in enumerate(j['trip']['legs']):
            d = decode6(leg['shape'])
            pts += d if li == 0 else d[1:]
        print(json.dumps(pts))
    else:
        print(__doc__); sys.exit(1)

if __name__ == '__main__':
    main()
