/* オービスデータとナビの判定ロジックの自動テスト。
   tests/run.sh から実行する（index.html のスクリプト部分を取り出して読み込む）。
   失敗が1つでもあれば終了コード1。データを更新したら必ず通すこと。 */
const fs = require('fs'), path = require('path');
const M = require('./.app.js');
const fails = [], notes = [];
const ok = (cond, msg) => { if (!cond) fails.push(msg); };

const on = {}; Object.keys(M.LAYERS).forEach(k => on[k] = true);
const ORBIS = M.POINTS.filter(p => p.type === 'orbis');

/* ---- 1. データの形 ---- */
const ids = new Set();
for (const p of M.POINTS){
  ok(!ids.has(p.id), `idの重複: ${p.id}`); ids.add(p.id);
  ok(M.LAYERS[p.layer], `${p.id}: 未定義のレイヤー ${p.layer}`);
  ok(p.lat > 20 && p.lat < 46 && p.lon > 122 && p.lon < 154, `${p.id}: 緯度経度が日本の範囲外`);
  ok(p.dir >= 0 && p.dir < 360, `${p.id}: dir が 0〜359 でない`);
  ok(Array.isArray(p.road) && p.road.length, `${p.id}: road（道路名キーワード）がない`);
  if (p.type === 'orbis'){
    ok(p.unc > 0, `${p.id}: unc がない`);
    ok(p.limit > 0, `${p.id}: limit がない`);
    ok(Array.isArray(p.warn) && p.warn.length, `${p.id}: warn がない`);
    ok(typeof p.src === 'string' && p.src.length > 4, `${p.id}: src（根拠）がない`);
    const line = M.APPROACH[p.id];
    ok(line && line.length >= 5, `${p.id}: APPROACH（手前の車線の線）がない、または短い`);
    if (line && line.length >= 2){
      ok(M.distToLine(p, line) <= 30, `${p.id}: オービス位置が APPROACH の線から30m以上離れている`);
      const a = { lat:line[0][0], lon:line[0][1] }, b = { lat:line[line.length-1][0], lon:line[line.length-1][1] };
      let len = 0; for (let i = 1; i < line.length; i++) len += M.dist({lat:line[i-1][0],lon:line[i-1][1]}, {lat:line[i][0],lon:line[i][1]});
      ok(len >= 1400, `${p.id}: APPROACH が1.4km未満（${Math.round(len)}m）`);
      const end = line.length - 1, k = Math.max(0, end - 3);
      const d2 = M.bearing({lat:line[k][0],lon:line[k][1]}, {lat:line[end][0],lon:line[end][1]});
      ok(M.angDiff(d2, p.dir) <= 50, `${p.id}: APPROACH の向き(${Math.round(d2)}°)と dir(${p.dir}°)が合わない`);
    }
  } else {
    ok(p.radius > 0 && p.msg, `${p.id}: 予告の radius / msg がない`);
  }
}

/* ---- 2. 各レイヤーの道路線で検証 ---- */
function loadFixture(layer){
  const f = path.join(__dirname, 'fixtures', layer + '.json');
  if (!fs.existsSync(f)) return null;
  const j = JSON.parse(fs.readFileSync(f, 'utf8'));
  const coords = j.shape.map(([lat, lon]) => ({ lat, lon }));
  const cum = [0]; for (let i = 1; i < coords.length; i++) cum.push(cum[i-1] + M.dist(coords[i-1], coords[i]));
  return { coords, cum, maneuvers:[{ begin:0, streets:j.streets, type:1, text:'' }], roads:[] , streets:j.streets };
}
function gauss(){ let u = 0, v = 0; while (!u) u = Math.random(); while (!v) v = Math.random(); return Math.sqrt(-2*Math.log(u))*Math.cos(2*Math.PI*v); }

const layers = [...new Set(ORBIS.map(p => p.layer))];
for (const layer of layers){
  const R = loadFixture(layer);
  ok(R, `レイヤー ${layer} の道路線 tests/fixtures/${layer}.json がない（新しい路線を追加したら作ること）`);
  if (!R) continue;
  const total = R.cum[R.cum.length-1];
  const found = M.pointsOnRoute(R, M.POINTS, on);
  const foundIds = found.map(o => o.point.id);
  for (const p of ORBIS.filter(p => p.layer === layer)) ok(foundIds.includes(p.id), `${p.id}: 自レイヤーの道路線上で見つからない（位置・dir・roadを確認）`);
  for (const id of foundIds){ const p = M.POINTS.find(x => x.id === id); if (p.type === 'orbis') ok(p.layer === layer, `${layer} の道路線上に別レイヤーの ${id} が載っている（反対車線の取り違えの疑い）`); }

  // 一般道の名前のルートでは載らないこと（真下を走る一般道で誤警告しない）
  const Rs = { ...R, maneuvers:[{ begin:0, streets:['テスト一般道'], type:1, text:'' }] };
  ok(M.pointsOnRoute(Rs, M.POINTS, on).filter(o => o.point.type === 'orbis').length === 0, `${layer}: 一般道名のルートでもオービスが載ってしまう`);

  // 60km/hで走行（山手トンネル内はGPSなし）。警告が遅れないこと
  const realAt = {}; found.forEach(o => realAt[o.point.id] = o.along);
  const E = M.createEngine(); E.setRoute(R, M.POINTS, on);
  let s = 0, t = 0; const got = {};
  for (let k = 0; k < 20000 && s < total - 20; k++){
    s += 16.7 * 0.5; t += 500;
    const p = M.pointAt(R, s);
    const res = M.inYamateTunnel(p.pos) ? E.tick(t, M.POINTS, on)
      : E.gps({ lat:p.pos.lat + gauss()*6/110540, lon:p.pos.lon + gauss()*6/90000, acc:10, heading:p.heading, speed:16.7, t }, M.POINTS, on);
    if (!res) continue;
    for (const a of res.alerts){
      if (a.kind !== 'orbis') continue;
      (got[a.point.id] = got[a.point.id] || []).push(a.thr);
      const remain = realAt[a.point.id] - s;
      ok(remain >= a.thr - 60, `${a.point.id}: ${a.thr}m警告が遅い（実際の残り${Math.round(remain)}m）`);
    }
  }
  for (const o of found.filter(o => o.point.type === 'orbis')){
    // 道筋の始点に近すぎるものは警告距離が取れないので対象外
    if (o.along < Math.max(...o.point.warn) + (o.point.unc || 0)) { notes.push(`${o.point.id}: 道路線の始点に近いため走行テスト省略`); continue; }
    for (const thr of o.point.warn) ok((got[o.point.id] || []).includes(thr), `${o.point.id}: ${thr}m警告が出なかった`);
  }

  // 逆走：ルートを逆向きに走ったら「ルート上」と判定せず、逆走として扱う
  {
    const E4 = M.createEngine(); E4.setRoute(R, M.POINTS, on);
    let s4 = Math.min(total - 50, 3000), t4 = 0, snapAfter = 0, ww = 0, n4 = 0;
    for (let k = 0; k < 120 && s4 > 50; k++){
      s4 -= 8.35; t4 += 500; const p = M.pointAt(R, s4);
      if (M.inYamateTunnel(p.pos)) continue;
      const r = E4.gps({ lat:p.pos.lat, lon:p.pos.lon, acc:10, heading:(p.heading + 180) % 360, speed:16.7, t:t4 }, M.POINTS, on);
      if (!r) continue; n4++;
      if (n4 > 3){ if (r.mode === 'snap') snapAfter++; if (r.wrongWay) ww++; }
    }
    ok(snapAfter === 0, `${layer}: 逆走しているのに「ルート上」と判定された（${snapAfter}回）`);
    ok(ww > 0, `${layer}: 逆走を検出できなかった`);
  }

  // ルートなし：約60m横の並走道路では警告しない
  for (const p of ORBIS.filter(p => p.layer === layer)){
    const line = M.APPROACH[p.id]; if (!line) continue;
    const E2 = M.createEngine(); let t2 = 0, n = 0;
    const off = 60 / 110540, h = M.bearing({lat:line[0][0],lon:line[0][1]}, {lat:line[line.length-1][0],lon:line[line.length-1][1]});
    const dx = Math.cos(rad(h + 90)), dy = Math.sin(rad(h + 90)); // 進行方向の右側へ60m
    for (const [lat, lon] of line){ t2 += 1000; const r = E2.gps({ lat:lat + dx*off, lon:lon + dy*off*1.23, acc:8, heading:null, speed:15, t:t2 }, M.POINTS, on); if (r) n += r.alerts.length; }
    ok(n === 0, `${p.id}: 約60m横の道路で誤警告する`);
  }

  // ルートなし：山手トンネル内のオービスは、真上（約15m横）の山手通りを走っても警告しない
  for (const p of ORBIS.filter(p => p.layer === layer && M.inYamateTunnel(p))){
    const line = M.APPROACH[p.id]; if (!line) continue;
    const E3 = M.createEngine(); let t3 = 0, n = 0;
    for (const [lat, lon] of line){ t3 += 1000; const r = E3.gps({ lat:lat + 15/110540, lon, acc:8, heading:null, speed:12, t:t3 }, M.POINTS, on); if (r) n += r.alerts.filter(a => a.kind === 'orbis').length; }
    ok(n === 0, `${p.id}: トンネル真上の一般道で誤警告する`);
  }
}
function rad(d){ return d*Math.PI/180; }

/* ---- 2b. 首都高の料金（概算） ---- */
ok(M.shutokoToll(1) === 280, '首都高：短距離は下限280円');
ok(M.shutokoToll(55) === 1740 && M.shutokoToll(90) === 1740, '首都高：55km以上は上限1,740円');
ok(Math.round((150 + 32.472 * 20) * 1.1 / 10) * 10 === 880, '首都高：普通車20kmが公表値880円と一致（式の確認）');
{
  const j = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'c2in.json'), 'utf8'));
  const coords = j.shape.map(([lat, lon]) => ({ lat, lon })); const cum = [0];
  for (let i = 1; i < coords.length; i++) cum.push(cum[i-1] + M.dist(coords[i-1], coords[i]));
  const half = Math.floor(coords.length / 2);
  const R = { coords, cum, maneuvers:[{ begin:0, streets:['C2','首都高速中央環状線'] }, { begin:half, streets:['山手通り'] }, { begin:half + 40, streets:['C2','首都高速中央環状線'] }] };
  const tl = M.routeTolls(R);
  ok(tl.shutoko.length === 2, `首都高を途中で降りて乗り直すと2回分になる（${tl.shutoko.length}回）`);
  ok(tl.total === tl.shutoko.reduce((s, x) => s + M.shutokoToll(x.km), 0), '首都高：合計が各回の合計と一致');
}

/* ---- 2b'. 首都高の料金：有料・自動車専用の印があるルート（路線記号だけの区間も続きとして数える） ---- */
{
  const j = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'c2in.json'), 'utf8'));
  const coords = j.shape.map(([lat, lon]) => ({ lat, lon })); const cum = [0];
  for (let i = 1; i < coords.length; i++) cum.push(cum[i-1] + M.dist(coords[i-1], coords[i]));
  const n = coords.length, q = Math.floor(n / 6);
  const R = { coords, cum, maneuvers:[
    { begin:0,   streets:['4', '昭和通り', '一般国道4号'] },
    { begin:q,   streets:['首都高速1号上野線'], toll:true, hwy:true },
    { begin:2*q, streets:['11'], hwy:true },                       // 印が「自動車専用」だけ・名前は記号だけ
    { begin:3*q, streets:['B'], toll:true, hwy:true },             // 名前は記号だけ
    { begin:4*q, streets:[], toll:true },                           // 出口
    { begin:4*q + 3, streets:['環七通り'] } ] };
  const tl = M.routeTolls(R), km = (cum[4*q + 3] - cum[q]) / 1000;
  ok(tl.shutoko.length === 1 && Math.abs(tl.shutoko[0].km - km) < 0.05, `首都高：路線記号だけの区間も1回の利用として続けて数える（${tl.shutoko.length}回・${tl.shutoko[0] ? tl.shutoko[0].km.toFixed(1) : '-'}km／正しくは${km.toFixed(1)}km）`);
  const R2 = { coords, cum, maneuvers:[{ begin:0, streets:['一般道'] }, { begin:q, streets:['E83', '第三京浜道路'], toll:true, hwy:true }, { begin:3*q, streets:['一般道'] }] };
  const t2 = M.routeTolls(R2);
  ok(t2.shutoko.length === 0 && t2.others.length === 1, '首都高以外の有料道路は、首都高の料金に含めず「未対応」に回す');
}

/* ---- 2c. 声でメモ ---- */
{
  const V = () => M.createVoiceMemo({ silence:10000 });
  let v = V(), e;
  e = v.feed('メモ開始', 0); ok(e.length === 1 && e[0].type === 'start' && v.on, '声メモ：「メモ開始」で録音が始まる');
  v.feed('再検索でUターンしろと言われた', 2000);
  e = v.feed('メモ終了', 4000); ok(e.length === 1 && e[0].type === 'save' && e[0].text === '再検索でUターンしろと言われた' && !v.on, '声メモ：「メモ終了」でそこまでを保存');
  v = V(); e = v.feed('メモ、スタート。右折の案内が遅い。メモ終了。', 0);
  ok(e.map(x => x.type).join() === 'start,save' && e[1].text === '右折の案内が遅い', '声メモ：1回の発話で開始〜終了');
  v = V(); e = v.feed('メモ 開始します 交差点の名前が違う', 0);
  ok(e.length === 1 && v.on && v.text === '交差点の名前が違う', '声メモ：「開始します」の言い方でも始まり、続きの言葉は本文になる');
  ok(v.tick(5000).length === 0, '声メモ：黙って5秒では保存しない');
  e = v.tick(10500); ok(e.length === 1 && e[0].type === 'save' && e[0].auto && e[0].text === '交差点の名前が違う', '声メモ：「メモ終了」を言い忘れても10秒黙ると自動保存');
  v = V(); v.feed('メモ開始', 0); v.feed('やっぱりいい', 1000); e = v.feed('メモ取り消し', 2000);
  ok(e.length === 1 && e[0].type === 'cancel' && !v.on, '声メモ：「メモ取り消し」で保存しない');
  v = V(); v.feed('めも開始', 0); v.feed('ナビの声が小さい', 500); e = v.feed('以上', 1000);
  ok(e.length === 1 && e[0].type === 'save' && e[0].text === 'ナビの声が小さい', '声メモ：ひらがなの「めも」と、「以上」だけでも終われる');
  v = V(); ok(v.feed('今日は寒いね、メモリが足りない', 0).length === 0 && !v.on, '声メモ：普通の会話では始まらない');
  v = V(); v.feed('メモ開始', 0); e = v.tick(11000); ok(e.length === 1 && e[0].type === 'empty', '声メモ：何も言わなければ空として終わる');
  v = V(); v.feed('メモ開始', 0); v.feed('ここ', 1000); v.feed('メモ開始 遅い', 2000); e = v.feed('メモ終了', 3000);
  ok(e[0].type === 'save' && e[0].text === 'ここ 遅い', '声メモ：録音中の「メモ開始」の言い直しは本文に入れない');
}

/* ---- 2d. 検索結果のまとめ・自動車専用道路の回避地点 ---- */
{
  ok(M.looksAddress('墨田区石原1-1') && M.looksAddress('新宿3丁目') && M.looksAddress('東京都千代田区丸の内１丁目９−１'), '検索：番地までの住所を住所と判定する');
  ok(!M.looksAddress('東京タワー') && !M.looksAddress('羽田空港第1ターミナル') && !M.looksAddress('セブンイレブン 梅島') && !M.looksAddress('道の駅 八王子滝山'), '検索：施設名を住所と判定しない');
  const here = { lat:35.70, lon:139.76 };
  const n = [{ lat:'35.6586', lon:'139.7454', name:'東京タワー', display_name:'東京タワー, 芝公園四丁目, 港区, 東京都' }];
  const ph = { features:[
    { properties:{ countrycode:'JP', name:'東京タワー', osm_value:'tower', state:'東京都' }, geometry:{ coordinates:[139.7455, 35.6587] } },
    { properties:{ countrycode:'JP', name:'東京タワー', osm_value:'bus_stop', state:'東京都' }, geometry:{ coordinates:[139.7480, 35.6570] } },
    { properties:{ countrycode:'US', name:'Tokyo Tower Cafe' }, geometry:{ coordinates:[-100, 40] } } ] };
  const g = [{ geometry:{ coordinates:[141.35, 43.06] }, properties:{ title:'北海道札幌市東区' } }, { geometry:{ coordinates:[139.7985, 35.7003] }, properties:{ title:'東京都墨田区石原一丁目１番' } }];
  const a = M.mergePlaces(n, ph, null, here, false);
  ok(a.length === 2 && a[0].src === 'n' && a[1].weak, `検索：同じ場所の重複をまとめ、バス停などは後ろに回す（${a.length}件）`);
  const b = M.mergePlaces(n, null, g, here, true);
  ok(b[0].src === 'g' && b[0].name.includes('石原') && !b.some(x => x.name.includes('札幌')), '検索：住所の検索では国土地理院の結果を先頭にし、遠すぎる地名は外す');
  ok(M.mergePlaces(null, null, null, here, false).length === 0, '検索：どの検索先も空なら0件');

  const j = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'c2in.json'), 'utf8'));
  const coords = j.shape.map(([lat, lon]) => ({ lat, lon })); const cum = [0];
  for (let i = 1; i < coords.length; i++) cum.push(cum[i-1] + M.dist(coords[i-1], coords[i]));
  const q = Math.floor(coords.length / 4);
  const R = { coords, cum, maneuvers:[{ begin:0, streets:['一般道'], hwy:false }, { begin:q, streets:['無料の自動車専用道路'], hwy:true }, { begin:2*q, streets:['一般道'], hwy:false }] };
  const locs = M.hwyLocs(R), lenKm = (cum[2*q] - cum[q]) / 1000;
  ok(locs.length >= 1 && locs.length <= Math.ceil(lenKm) + 1 && locs.every(l => l.search_filter.min_road_class === 'motorway'), `自動車専用道路の区間だけに、避ける地点を約1kmおきに置く（${locs.length}か所／${lenKm.toFixed(1)}km）`);
  ok(M.hwyLocs({ coords, cum, maneuvers:[{ begin:0, streets:['一般道'] }] }).length === 0, '自動車専用道路が無ければ、避ける地点は作らない');
}

/* ---- 3. 速度取締りエリアのデータ（警視庁 月次） ---- */
{
  const f = path.join(__dirname, '..', 'data', 'speed', 'latest.json');
  ok(fs.existsSync(f), 'data/speed/latest.json がない');
  if (fs.existsSync(f)){
    const d = JSON.parse(fs.readFileSync(f, 'utf8'));
    ok(/^\d{4}-\d{2}$/.test(d.month), '取締りデータの month が「年-月」形式でない');
    ok(Array.isArray(d.areas) && d.areas.length >= 10, `取締りエリアが少なすぎる（${(d.areas || []).length}か所）`);
    ok(d.roads && d.roads.features && d.roads.features.length > 0, '取締りエリアの道路が空');
    for (const a of d.areas || []) ok(a.geom && /Polygon/.test(a.geom.type) && a.route && a.place, `取締りエリア ${a.id} の形が不正`);
    const size = fs.statSync(f).size; ok(size < 4_000_000, `取締りデータが大きすぎる（${size}バイト）`);
  }
}

notes.forEach(n => console.log('  メモ: ' + n));
if (fails.length){ console.log('NG（' + fails.length + '件）'); fails.forEach(f => console.log('  ✗ ' + f)); process.exit(1); }
console.log(`OK：オービス${ORBIS.length}か所／予告${M.POINTS.length - ORBIS.length}か所／検証した路線 ${layers.join(', ')}`);
