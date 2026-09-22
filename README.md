# grok-4.6-4.7-comparison

Grok 4.6 と Grok 4.7 の性能・速度・コストを、`reasoning_effort` の `high` / `xhigh` で比較するベンチマーク。公式 `xai_sdk` (Python, AsyncClient) を使用。

## 比較対象

| モデル | reasoning_effort |
| --- | --- |
| `grok-4.6` | `high`, `xhigh` |
| `grok-4.7` | `high`, `xhigh` |

4 コンボ（モデル × effort）を全データセットで評価する。

## ベンチマーク

`benchmarks/` 以下のデータセットを使用する。詳細は [benchmarks/README.md](benchmarks/README.md) を参照。

- `translator-ja-en.jsonl` — 日本語→英語 翻訳（10サンプル、単語集合 F1）
- `arithmetic.jsonl` — 多段階四則・分数・入れ子括弧・大きな数（17サンプル、数値誤差 1e-6；1回難易度引き上げ後）
- `differential.jsonl` — 微分方程式 / 微積分（14サンプル、数値または正規化文字列；1回難易度引き上げ後）
- `terminal.jsonl` — 安全な bash スクリプト生成（13サンプル、一時ディレクトリで実行してファイル/stdout を検査；1回難易度引き上げ後）

各サンプルについてレイテンシ、入出力・reasoning トークン、USD コスト、正解スコアを記録し、`(データセット, モデル, reasoning_effort)` ごとに平均を集計する。

全コンボの平均スコアが 0.95 以上のデータセットは、より難しいサンプルを 1 ラウンドだけ追加して再実行する。

## コスト計算

両モデルとも（プロンプト 200k 未満）:

- 入力: **$2 / 1M tokens**
- 出力: **$6 / 1M tokens**

`response.usage` を使い、`prompt_tokens`（または input）と `completion_tokens`（または output）を読む。`reasoning_tokens` は出力として課金されるが、`total_tokens == prompt + completion` で reasoning が completion の内数なら **二重計上しない**。completion に含まれていない場合のみ出力トークンに加算する。

コンボごとに `avg_prompt_tokens`, `avg_completion_tokens`, `avg_reasoning_tokens`, `avg_total_tokens`, `total_cost_usd`, `avg_cost_usd` を記録する。

## セットアップ

```bash
uv sync
```

xAI の API キーを環境変数、または `.env` ファイルに設定する（`.env` は git 管理しない）。

```bash
export XAI_API_KEY="your_api_key"
```

このリポジトリには API キーを置かないこと。

## 実行方法

全データセット・全モデル・全 reasoning_effort を実行:

```bash
uv run main.py --output results.json
uv run viewer.py results.json -o results.html
cp results.html index.html
```

対象を絞る例:

```bash
uv run main.py --datasets arithmetic --models grok-4.7 --concurrency 3
uv run main.py --limit 3
```

### オプション一覧

| オプション | 説明 | デフォルト |
| --- | --- | --- |
| `--datasets` | 実行するデータセット名（複数指定可） | 全データセット |
| `--models` | 実行するモデル名（複数指定可） | `grok-4.6 grok-4.7` |
| `--limit` | 各データセットから使うサンプル数 | 制限なし（全件） |
| `--concurrency` | 同時リクエスト数 | `3` |
| `--output` | 結果を JSON で保存するパス | 保存しない |
| `--no-escalate` | 高スコア時の難易度引き上げをしない | オフ |

## ビューワ

`results.json` から GitHub Pages 向けの静的 HTML を生成する。

```bash
uv run viewer.py results.json -o results.html
```

`index.html` は `results.html` のコピー（Pages のルート公開用）。

## 注意

- 全パターン実行すると 4 コンボ × 4 データセット × 約 10〜12 サンプル で 160 回前後の API リクエストが発生する。`xhigh` は時間がかかる。課金と実行時間に注意すること。
- terminal ベンチは生成スクリプトを一時ディレクトリで実行する。`sudo` / `curl` / `wget` / `ssh` / `rm -rf /` や一時ディレクトリ外への書き込みを含むスクリプトは棄却する。
