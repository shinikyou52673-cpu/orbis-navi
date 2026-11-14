# オービスナビ — 作業手順書

GitHub Pages で公開している、iPhone（Chrome / Safari）向けのバイク用ナビWebアプリです。
`index.html` 1枚で動きます（地図：MapLibre＋OpenFreeMap、ルート：Valhalla、検索：Nominatim）。
`main` ブランチに push すると、1〜2分で公開URLに反映されます。**走行中に使われるものなので、壊さないことが最優先**です。

## 自動更新（定期実行）の目的

次の2つを、根拠を残しながら少しずつ良くすることです。

1. **使い勝手**：利用者の改善メモと走行記録をもとに、案内・表示・操作の不具合や使いにくさを直す（**優先**）
2. **オービスデータ**：精度と収録範囲を上げる

1回の実行で扱うのは、フィードバック由来の問題1〜2件、または `docs/BACKLOG.md` の上から1〜2項目までにします。

### 定例作業（毎回の最初に確認）
- **速度取締り実施エリア（警視庁の月次公表）**
  - 警視庁の公開交通取締りページ（`tools/police_speed.py` の PAGE_URL）のPDF「○月中の速度取締実施場所一覧」の月が、`data/speed/latest.json` の `month` より新しければ更新します
  - 手順：`pip install --break-system-packages shapely mapbox-vector-tile`（必要なら）→ `python3 tools/police_speed.py` → `bash tests/run.sh` → push
  - 見つからなかった場所（`missing`）は、CHANGELOG に件数を書きます。場所の書き方が新しくて読めない行があれば、`parse_pdf` / `place_queries` を直します
  - 古い月のファイル（`data/speed/YYYY-MM.json`）は、直近3か月分だけ残します

### フィードバック（改善メモ・走行記録）の扱い
- 置き場所は、非公開リポジトリ `shinikyou52673-cpu/orbis-navi-feedback` です（アクセスできない日は、この作業を飛ばします）
  - `memos/日付/*.json`：走行中・停車中に残した改善メモ（文字起こし、位置、ルート概要、直前の読み上げ）
  - `rides/日付/*.json`：案内1回分の走行記録（約2秒ごとの位置・判定、イベント：start / speak / reroute / wrongway / memo / arrive / end）
  - `memos/siri/日付_時刻.txt`：Siriのショートカット「ナビメモ」で話したメモ（本文だけのテキスト。ファイル名が日本時間の日時）。位置は、同じ時刻の走行記録から読み取ります
  - `diag/日付/*.json`：設定の「マイクと音声認識のテスト」の結果（音声認識の経過、マイクの音量、送信先の設定の有無）
  - `processed.json`：処理済みファイルの一覧。処理したら追記して、そのリポジトリに push します
- 読み方の目安
  - `reroute` で `uturn:true` → 再検索の指示がUターンだった
  - `wrongway` が出ているのに `reroute` が無い → 逆走の扱いの不具合
  - `mode` が `free` のまま長い → ルートへの吸着、またはルートの質の問題
  - メモの文面 → 利用者が困ったこと（最優先）
- **走行記録は個人の移動履歴です**
  - 公開リポジトリに、座標・時刻・走行記録そのものを書き写してはいけません
  - 記録してよいのは、`docs/UX_LOG.md` への「何が起きて、どう直したか」の要約だけです（地名は区レベルまで）
  - テストで再現が必要な場合は、公開の道路線（Valhallaの道筋）から作ります

### ルートの選び方（2026-11-13 に実測して決めた設定。変えるときは同じ測り方で比べること）
- `requestRoute` の `costing_options` は、次の2通りです
  - 有料も使う：`{ use_highways:1, use_distance:0.3 }`
  - 有料を使わない：`{ use_tolls:0, use_distance:0.3 }`
- `use_distance:0.3` を外すと、国道を大回りする道になります（例：北千住→錦糸町が7.9km・20分 → 10.9km・23分）
- `use_highways:0` は使いません。国道（幹線）まで避けて、細い道と右左折が増えます（例：蒲田→浅草が40分 → 61分）
- 比べ方：都内の6〜7区間で、所要時間・距離・右左折の回数・細い道の割合（`trace_attributes` の `edge.road_class`）を表にします

### 触ってよいもの
- `index.html` のデータ部分：`LAYERS`／`POINTS`／`APPROACH`／`YAMATE_TUNNEL`／`PRESETS`
- `index.html` のプログラム部分（フィードバックや BACKLOG「使い勝手」に書かれた問題を直す場合だけ）
  - 1件ずつ、小さく直す
  - 直したら `APP_VERSION` を今日の日付に更新する
- `tests/`（テストの追加は歓迎。直した不具合が再発しないテストを足す）、`docs/`、`CHANGELOG.md`

### 触らないもの
- 大きな作り直し、機能の削除
- 利用者が選んだ初期値の変更
  - 例：音の出し方の初期値「鳴らさない」は、利用者の明示的な希望です
- APIキーが必要な外部サービスの追加
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
python3 tests/ui_smoke.py                          # プログラムを変えたときは必須。NGなら push しない
git add -A && git commit -m "データ: <要約>"   # プログラム修正は「改善: <要約>」
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
