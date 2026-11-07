#!/usr/bin/env bash
# 反映前の自動テスト。リポジトリのルートで `bash tests/run.sh` を実行する。
set -euo pipefail
cd "$(dirname "$0")/.."
python3 - <<'EOF'
import re
html = open('index.html', encoding='utf-8').read()
scripts = re.findall(r'<script>(.*?)</script>', html, re.S)
assert len(scripts) == 1, 'インラインscriptが1つではありません'
open('tests/.app.js', 'w', encoding='utf-8').write(scripts[0])
size = len(html.encode('utf-8'))
assert size < 400_000, f'index.html が大きすぎます（{size}バイト）'
print(f'index.html {size}バイト')
EOF
node --check tests/.app.js && echo "構文チェック OK"
node tests/engine.test.js
