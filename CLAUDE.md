# オービスナビ — 作業手順書

GitHub Pages で公開している、iPhone（Chrome / Safari）向けのバイク用ナビWebアプリです。
`index.html` 1枚で動きます（地図：MapLibre＋OpenFreeMap、ルート：Valhalla、検索：Nominatim）。
`main` ブランチに push すると、1〜2分で公開URLに反映されます。**走行中に使われるものなので、壊さないことが最優先**です。

## 自動更新（定期実行）の目的

オービスデータの**精度と収録範囲**を、根拠を残しながら少しずつ上げることです。
1回の実行で扱うのは `docs/BACKLOG.md` の上から1〜2項目までにします。

### 触ってよいもの
- `index.html` のデータ部分：`LAYERS`／`POINTS`／`APPROACH`／`YAMATE_TUNNEL`／`PRESETS`
- `tests/fixtures/*.json`（路線ごとの道路線）、`docs/BACKLOG.md`、`CHANGELOG.md`

### 触らないもの
- 画面・判定ロジック・ルート検索などのプログラム部分
  - バグや改善点を見つけたら、`docs/BACKLOG.md` の「要相談」に書くだけにする
- 既存のテストを、通すために弱めること

## 位置データのルール（最重要）

1. **根拠のない位置は入れません。** 位置の根拠として使えるのは次の3つだけです
   - (a) OpenStreetMap の分岐点・出入口・JCT（`tools/osm.py search`）に、出典の「○○出口の先」「約1km先」などの記述を当てはめて道路線上で計算したもの
   - (b) 出典ページに明記された座標（投稿者の座標など）
   - (c) 利用者がアプリの「修正した位置を書き出す」で渡した座標（最優先）
2. **オービスガイドの地点ページにある地図の中心座標は使いません。** 縮尺11の表示中心で、実際の位置から1〜2kmずれています（2026-11に確認済み）
3. 位置は必ず「通過する向きの車線」の道路線上に合わせます（`tools/approach.js` の `point`）
   - 首都高は上下線が15〜20mしか離れていない区間があります
4. `unc`（道なりの誤差の目安）は正直に付けます
   - 区間しか分からないときは、区間の中央に置いて `unc` を区間長の半分にします
   - 警告は `unc` の分だけ早まります（安全側）
5. `src` に根拠を書きます（出典名・年・どの記述から計算したか）
6. **撤去**は、日付のある信頼できる出典（報道・警察発表など）がある場合だけ反映します
   - データは消さずに `CHANGELOG.md` に記録します
   - 撤去済みの地点は `POINTS` から外し、BACKLOG に経緯を書きます
7. 推測で埋めません。判断できなければ BACKLOG に「未確定」と理由を書いて終わります

## 新しいオービス・路線を追加する手順

1. 出典を調べます（WebSearch / WebFetch）。新設・撤去は日付を確認します
2. その方向に通過する道筋を取ります
   ```
   python3 tools/osm.py route body.json > route.json   # 例は tools/osm.py の冒頭を参照
   python3 tools/osm.py shape route.json > shape.json
   ```
   - 道筋はオービスの**2km以上手前**から始めます。高速本線に吸着させるため、`search_filter:{min_road_class:'motorway',exclude_ramp:true}` と `heading` を付けます
3. `node tools/approach.js shape.json <lat> <lon> <unc>` を実行します
   - 出力の `point` → `POINTS` の lat/lon/dir
   - 出力の `approach` → `APPROACH[id]`
   - `snapDistance` が大きいとき、または `warning` が出たときは道筋を取り直します
4. `POINTS` に追加します
   - 必須：`id, layer, type:'orbis', name, lat, lon, dir, unc, limit, warn, road, info, src`
   - `road` は、その道路の Valhalla の street_names に含まれる語にします（例：`['中央環状','C2']`）
5. 新しい路線（レイヤー）なら、次の2つを行います
   - `LAYERS` に追加する
   - `tests/fixtures/<layer>.json`（`{note, streets, shape}`、その路線の道筋）を作る
6. トンネル内のオービスがあれば、入口の約500m手前に `type:'announce'` の予告を置きます

## 反映（push）の手順

```
git fetch origin main && git rebase origin/main   # 利用者が手動でアップロードしていることがある
bash tests/run.sh                                  # 必ず通すこと。NGなら push しない
git add -A && git commit -m "データ: <要約>"
git push origin HEAD:main
```
- force push は禁止です
- rebase で `index.html` が衝突したら中止します（`git rebase --abort`）。利用者の変更を上書きせず、報告だけします
- テストがNGのまま push してはいけません。原因を BACKLOG に書いて終わります
- `CHANGELOG.md` の先頭に、日付・変更内容・根拠・`unc` を追記します（利用者が後から読む前提で、平易な日本語で書きます）

## ネットワークの注意
- 作業環境の `curl` からは OSM 系サービス（Overpass 等）に届かないことがあります。Valhalla / Nominatim は `tools/osm.py`（ヘッドレスChrome経由）を使います
- サーバー負荷を避けるため、リクエストは1秒以上あけます
- Overpass API は届かない前提で考えます

## このリポジトリは公開です
個人情報（住所・氏名・勤務先など）を、コード・コミット・ドキュメントに書かないでください。
