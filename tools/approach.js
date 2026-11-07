#!/usr/bin/env node
/* オービス手前の「車線の線」（APPROACH）と、道路上の正確な位置を作る小道具。
   使い方:
     node tools/approach.js <shape.json> <lat> <lon> <unc>
       shape.json … tools/osm.py shape で作った、オービスを通過する向きの道筋
       lat lon    … オービスの推定位置（道路から多少ずれていてよい）
       unc        … 道なりの誤差の目安(m)
     node tools/approach.js <shape.json> --along <道のり(m)>
       道筋の始点から指定距離の地点（例：分岐点＋1km）を出す
   出力: 道路上に合わせた位置・進行方向・APPROACH用の線(JSON) */
const fs = require('fs');
const R = 6371000, rad = d => d * Math.PI / 180;
const dist = (a, b) => { const dLa = rad(b[0]-a[0]), dLo = rad(b[1]-a[1]); const h = Math.sin(dLa/2)**2 + Math.cos(rad(a[0]))*Math.cos(rad(b[0]))*Math.sin(dLo/2)**2; return 2*R*Math.asin(Math.sqrt(h)); };
const brg = (a, b) => { const y = Math.sin(rad(b[1]-a[1]))*Math.cos(rad(b[0])); const x = Math.cos(rad(a[0]))*Math.sin(rad(b[0])) - Math.sin(rad(a[0]))*Math.cos(rad(b[0]))*Math.cos(rad(b[1]-a[1])); return (Math.atan2(y, x)*180/Math.PI + 360) % 360; };

const shape = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const cum = [0]; for (let i = 1; i < shape.length; i++) cum.push(cum[i-1] + dist(shape[i-1], shape[i]));
const total = cum[cum.length-1];
function at(m){
  m = Math.max(0, Math.min(total, m));
  for (let i = 1; i < shape.length; i++) if (cum[i] >= m){
    const t = (m - cum[i-1]) / ((cum[i] - cum[i-1]) || 1);
    return { lat:+(shape[i-1][0] + (shape[i][0]-shape[i-1][0])*t).toFixed(6), lon:+(shape[i-1][1] + (shape[i][1]-shape[i-1][1])*t).toFixed(6), dir:Math.round(brg(shape[i-1], shape[i])) };
  }
  const n = shape.length; return { lat:shape[n-1][0], lon:shape[n-1][1], dir:Math.round(brg(shape[n-2], shape[n-1])) };
}
function project(p){
  let best = { d:Infinity };
  for (let i = 0; i < shape.length-1; i++){
    const a = shape[i], b = shape[i+1], kx = Math.cos(rad(a[0]))*111320, ky = 110540;
    const qx = (b[1]-a[1])*kx, qy = (b[0]-a[0])*ky, px = (p[1]-a[1])*kx, py = (p[0]-a[0])*ky;
    const L = qx*qx + qy*qy; let t = L ? (px*qx + py*qy)/L : 0; t = Math.max(0, Math.min(1, t));
    const d = Math.hypot(px - t*qx, py - t*qy);
    if (d < best.d) best = { d, along: cum[i] + t*(cum[i+1]-cum[i]) };
  }
  return best;
}
if (process.argv[3] === '--along'){
  const m = +process.argv[4];
  console.log(JSON.stringify({ along:m, total:Math.round(total), point:at(m) }));
  process.exit(0);
}
const lat = +process.argv[3], lon = +process.argv[4], unc = +(process.argv[5] || 300);
const pr = project([lat, lon]);
const snapped = at(pr.along);
const from = Math.max(0, pr.along - 1500 - unc), to = Math.min(total, pr.along + 150);
const line = []; for (let s = from; s <= to; s += 100){ const q = at(s); line.push([q.lat, q.lon]); }
const e = at(to); line.push([e.lat, e.lon]);
console.log(JSON.stringify({ snapDistance:Math.round(pr.d), along:Math.round(pr.along), total:Math.round(total),
  point:{ lat:snapped.lat, lon:snapped.lon, dir:at(pr.along + 20).dir }, approachLength:Math.round(to - from),
  warning: (pr.along - 1500 - unc) < 0 ? '道筋の始点が近すぎて手前の線が短い。もっと手前から道筋を取り直すこと' : undefined,
  approach:line }));
