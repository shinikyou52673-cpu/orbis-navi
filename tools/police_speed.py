#!/usr/bin/env python3
"""警視庁「速度取締実施場所一覧」（毎月公表のPDF）から、地図に塗るデータを作る。

  python3 tools/police_speed.py            # 最新のPDFを取得して data/speed/<年-月>.json と latest.json を作る
  python3 tools/police_speed.py --pdf x.pdf --month 2026-11   # 手元のPDFから作る

手順：PDF→表の行（行政区・実施路線・実施場所・所属）→ 丁目の境界（OSM／Nominatim）
     → 境界が無ければ地点の周り半径300m → 30m広げた範囲の道路を地図タイルから切り出す。
必要なもの：pdftotext、shapely、mapbox-vector-tile（pip install --break-system-packages shapely mapbox-vector-tile）
"""
import argparse, datetime, json, math, os, re, subprocess, sys, time, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_URL = 'https://www.keishicho.metro.tokyo.lg.jp/kotsu/torishimari/kokai_juten/kokai.files/speeding.pdf'
PAGE_URL = 'https://www.keishicho.metro.tokyo.lg.jp/kotsu/torishimari/kokai_juten/kokai.html'
UA = 'orbis-navi-data-build (github.com/shinikyou52673-cpu/orbis-navi)'
KANJI = '〇一二三四五六七八九'
ROAD_CLASSES = {'trunk', 'primary', 'secondary', 'tertiary', 'minor', 'service', 'busway'}

def http(url, binary=False):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'ja'})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = r.read()
    return data if binary else data.decode('utf-8')

def z2h(s):
    return s.translate(str.maketrans('０１２３４５６７８９－', '0123456789-'))

def num2kanji(n):
    n = int(n)
    if n < 10: return KANJI[n]
    if n < 20: return '十' + (KANJI[n-10] if n > 10 else '')
    return KANJI[n//10] + '十' + (KANJI[n%10] if n % 10 else '')

# ---------- PDF → 行 ----------
def parse_pdf(path):
    txt = subprocess.run(['pdftotext', '-layout', path, '-'], capture_output=True, text=True, check=True).stdout
    month = None
    m = re.search(r'([０-９0-9]+)\s*月中の速度取締実施場所一覧', txt)
    if m: month = int(z2h(m.group(1)))
    rows = []
    for line in txt.splitlines():
        if '付近' not in line: continue
        cols = [c.strip() for c in re.split(r'\s{2,}', line.strip()) if c.strip()]
        i = next((k for k, c in enumerate(cols) if '付近' in c), None)
        if i is None or i == 0: continue
        place = cols[i]
        route = cols[i-1]
        if ' ' in place or '　' in place:                        # 路線名と場所が1つの欄に混ざった場合
            parts = re.split(r'[ 　]+', place); place = parts[-1]; extra = ' '.join(parts[:-1])
            route = extra if re.fullmatch(r'\S{1,5}[区市町村]', route) else (route + ' ' + extra).strip()
        station = re.sub(r'\s+', '', ''.join(cols[i+1:])) if i + 1 < len(cols) else ''
        rows.append({'route': route, 'place': place, 'station': station})
    return month, rows

# ---------- 住所 → 範囲 ----------
def place_queries(place):
    p = z2h(place).replace('付近', '').strip()
    p = re.sub(r'(\d+)目$', r'\1丁目', p)                      # 「４目」の誤記
    qs = []
    m = re.match(r'^(.+?[区市町村])(.+?)(\d+)丁目(?:(\d+)番)?$', p)
    if m:
        ward, town, cho = m.group(1), m.group(2), m.group(3)
        qs.append(('chome', f'東京都{ward}{town}{num2kanji(cho)}丁目'))
        qs.append(('town', f'東京都{ward}{town}'))
    else:
        m = re.match(r'^(.+?[区市町村])(.+?)(\d+)番$', p)
        if m:
            qs.append(('town', f'東京都{m.group(1)}{m.group(2)}'))
        else:
            qs.append(('place', f'東京都{p}'))
    return p, qs

def nominatim(q):
    url = 'https://nominatim.openstreetmap.org/search?format=jsonv2&polygon_geojson=1&limit=5&countrycodes=jp&q=' + urllib.parse.quote(q)
    time.sleep(1.1)
    return json.loads(http(url))

def area_km2(geom):
    from shapely.geometry import shape
    g = shape(geom); lat = g.centroid.y
    return g.area * (111.32 * math.cos(math.radians(lat))) * 110.54

def geocode(place):
    from shapely.geometry import shape, Point, mapping
    norm, qs = place_queries(place)
    for kind, q in qs:
        try: res = nominatim(q)
        except Exception as e: print('  検索失敗', q, e, file=sys.stderr); continue
        for r in res:
            g = r.get('geojson') or {}
            if g.get('type') in ('Polygon', 'MultiPolygon') and r.get('category') in ('boundary', 'place') and area_km2(g) < 3.0:
                return {'method': 'polygon' if kind == 'chome' else 'town', 'query': q, 'geom': g}
        for r in res:
            if r.get('category') in ('boundary', 'place', 'leisure', 'aeroway', 'landuse') or kind == 'place':
                pt = Point(float(r['lon']), float(r['lat']))
                return {'method': 'point', 'query': q, 'geom': mapping(circle(pt, 300))}
    return None

def circle(pt, meters):
    from shapely.affinity import scale
    lat = pt.y
    return scale(pt.buffer(1.0, 32), meters / (111320 * math.cos(math.radians(lat))), meters / 110540)

def buffer_m(geom, meters):
    from shapely.geometry import shape
    from shapely.affinity import scale
    g = shape(geom); c = g.centroid
    kx, ky = 111320 * math.cos(math.radians(c.y)), 110540
    gm = scale(g, kx, ky, origin=(0, 0)).buffer(meters, 8)
    return scale(gm, 1 / kx, 1 / ky, origin=(0, 0))

# ---------- 範囲内の道路（地図タイルから切り出し） ----------
_tilejson = None; _tilecache = {}
def tile_url():
    global _tilejson
    if not _tilejson: _tilejson = json.loads(http('https://tiles.openfreemap.org/planet'))
    return _tilejson['tiles'][0]

def deg2tile(lat, lon, z):
    n = 2 ** z; x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y

def tile_lines(z, x, y):
    import mapbox_vector_tile
    key = (z, x, y)
    if key in _tilecache: return _tilecache[key]
    data = http(tile_url().format(z=z, x=x, y=y), binary=True)
    time.sleep(0.2)
    dec = mapbox_vector_tile.decode(data, default_options={'y_coord_down': True})
    out = []
    layer = dec.get('transportation', {})
    ext = layer.get('extent', 4096); n = 2 ** z
    def conv(c):
        lon = (x + c[0] / ext) / n * 360 - 180
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + c[1] / ext) / n))))
        return (lon, lat)
    for f in layer.get('features', []):
        cls = f['properties'].get('class')
        if cls not in ROAD_CLASSES: continue
        g = f['geometry']
        if g['type'] == 'LineString': parts = [g['coordinates']]
        elif g['type'] == 'MultiLineString': parts = g['coordinates']
        else: continue
        for part in parts:
            out.append((cls, [conv(c) for c in part]))
    _tilecache[key] = out
    return out

def roads_in(area, z=14):
    from shapely.geometry import LineString
    minx, miny, maxx, maxy = area.bounds
    x0, y1 = deg2tile(miny, minx, z); x1, y0 = deg2tile(maxy, maxx, z)
    feats = []
    for tx in range(x0, x1 + 1):
        for ty in range(y0, y1 + 1):
            for cls, coords in tile_lines(z, tx, ty):
                if len(coords) < 2: continue
                ln = LineString(coords)
                if not ln.intersects(area): continue
                clip = ln.intersection(area)
                geoms = [clip] if clip.geom_type == 'LineString' else [g for g in getattr(clip, 'geoms', []) if g.geom_type == 'LineString']
                for g in geoms:
                    if g.length < 1e-5: continue
                    feats.append((cls, [[round(a, 5), round(b, 5)] for a, b in g.coords]))
    return feats

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--pdf'); ap.add_argument('--month')
    a = ap.parse_args()
    from shapely.geometry import mapping
    pdf = a.pdf
    if not pdf:
        pdf = os.path.join('/tmp', 'speeding.pdf')
        open(pdf, 'wb').write(http(PDF_URL, binary=True))
    mnum, rows = parse_pdf(pdf)
    today = datetime.date.today()
    if a.month: month = a.month
    else:
        y = today.year + (1 if mnum and mnum < today.month - 6 else 0)
        month = f'{y}-{mnum:02d}' if mnum else today.strftime('%Y-%m')
    print(f'{month}：{len(rows)}か所', file=sys.stderr)
    areas, roads, miss = [], [], []
    for i, r in enumerate(rows):
        g = geocode(r['place'])
        if not g: miss.append(r['place']); print('  見つからない：', r['place'], file=sys.stderr); continue
        area = buffer_m(g['geom'], 30)                     # 隣接する道路も含める
        aid = f'a{i+1}'
        areas.append({'id': aid, 'route': r['route'], 'place': r['place'], 'station': r['station'], 'method': g['method'],
                      'geom': json.loads(json.dumps(mapping(area.simplify(0.00005)), default=float))})
        for cls, coords in roads_in(area):
            roads.append({'type': 'Feature', 'properties': {'a': aid, 'c': cls}, 'geometry': {'type': 'LineString', 'coordinates': coords}})
        print(f"  {r['place']}：{g['method']} / 道路{sum(1 for f in roads if f['properties']['a']==aid)}本", file=sys.stderr)
    out = {'month': month, 'source': PAGE_URL, 'pdf': PDF_URL, 'built': today.isoformat(),
           'note': '警視庁「速度取締実施場所一覧」の丁目（境界が無い場所は地点の周り300m）を30m広げた範囲と、その中の道路',
           'missing': miss, 'areas': areas, 'roads': {'type': 'FeatureCollection', 'features': roads}}
    os.makedirs(os.path.join(ROOT, 'data', 'speed'), exist_ok=True)
    for name in (f'{month}.json', 'latest.json'):
        with open(os.path.join(ROOT, 'data', 'speed', name), 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    cnt = {}
    for x in areas: cnt[x['method']] = cnt.get(x['method'], 0) + 1
    print(f'完了：範囲{len(areas)}／道路{len(roads)}本／見つからない{len(miss)}　内訳{cnt}', file=sys.stderr)

if __name__ == '__main__':
    main()
