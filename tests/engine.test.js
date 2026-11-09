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

notes.forEach(n => console.log('  メモ: ' + n));
if (fails.length){ console.log('NG（' + fails.length + '件）'); fails.forEach(f => console.log('  ✗ ' + f)); process.exit(1); }
console.log(`OK：オービス${ORBIS.length}か所／予告${M.POINTS.length - ORBIS.length}か所／検証した路線 ${layers.join(', ')}`);
