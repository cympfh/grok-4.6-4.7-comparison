# ベンチマークデータセット

各ファイルは JSON Lines 形式。1行が1サンプル。

## translator-ja-en.jsonl

日本語 → 英語の翻訳。10サンプル。既存の 4.3/4.5 比較から再利用。

- `input`: 日本語の文
- `expected`: 参考英訳
- 採点: 出力と参考英訳を単語集合に分解し、F1（単語の一致度）を 0.0〜1.0 のスコアとする。翻訳は表現が揺れるため厳密一致ではなく類似度で評価する。

## arithmetic.jsonl

多段階の四則演算。17 サンプル（初期12 + 難易度引き上げ5）。分数・入れ子括弧・大きな整数・べき乗を含む。

- `input`: 計算式（`+ - * / () ^` を含む）
- `expected`: 計算結果の数値（文字列）
- 採点: 出力から数値（分数 `a/b` も可）を抜き出し、`expected` と絶対誤差 1e-6 以内なら 1.0、そうでなければ 0.0。

参考プロジェクトの単純な四則より難しい式を使う。全コンボの平均スコアが 0.95 以上なら、さらに難しいサンプルを 1 ラウンド追加する。

## differential.jsonl

微分方程式・微積分。14 サンプル（初期10 + 難易度引き上げ4）。答えは一意な数値（または短い閉形式を数値評価したもの）。

- `input`: 問題文（英語）。数値だけを出力するよう指示
- `expected`: 数値
- 採点: 数値一致（絶対誤差 1e-6）または正規化した短文字列の一致。

例: `y'=2y, y(0)=1` の `y(ln 2)` は 4。

## terminal.jsonl

安全なシェル操作。16 サンプル。連番ファイル作成、計算結果の書き出し、ソート、連結、リネーム、サブディレクトリ、`seq`、python / awk、単語カウントに加え、`zip` でアーカイブ作成、`ln` でシンボリックリンク、`mkfifo` で名前付きパイプを含む。

- `input`: 空の一時ディレクトリで実行する bash スクリプトだけを ```bash ... ``` で出力するよう求める指示
- `check.files`: 作成されるべき相対パスと内容
- `check.stdout`: 標準出力の期待値（任意）
- `check.absent`: 存在してはいけない相対パス（任意）
- `check.symlinks`: シンボリックリンクの相対パスとリンク先
- `check.fifos`: FIFO であるべき相対パス
- `check.zip_members`: zip アーカイブ内のメンバー名と内容
- 採点: モデル出力からスクリプトを抽出し、禁止パターン（`sudo`, `curl`, `wget`, `ssh`, `rm -rf /` など、一時ディレクトリ外への書き込み）があれば 0.0。禁止がなければ空の一時ディレクトリで `bash` を timeout 10s・ネットワークなしで実行し、期待ファイル / stdout / symlink / FIFO / zip メンバーが一致すれば 1.0、そうでなければ 0.0。

## Escalation

See [ESCALATION.md](ESCALATION.md). Arithmetic and differential were escalated once during evaluation. The terminal set is the 16-sample suite above.
