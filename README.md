# DayTrade_Pro

デイトレード用スクリーニング・通知システム。

**発注機能はない。** 候補抽出・監視・通知のみ行う。売買の判断と執行は人間が手動で行う。

- 仕様: [`docs/daytrade-screening-spec.md`](docs/daytrade-screening-spec.md)（第7章の株数表に誤りあり。訂正は docs/02 参照）
- 事前調査と仕様書への指摘: [`docs/00_recon.md`](docs/00_recon.md)
- 第0層の実測と ILLIQ の修正: [`docs/01_layer0_findings.md`](docs/01_layer0_findings.md)
- 第1〜3層の実測: [`docs/02_layer123_findings.md`](docs/02_layer123_findings.md)

## 動作要件

Python 3.11 以上（開発・検証は 3.14.4）。**サードパーティ依存なし。**
`urllib` / `html.parser` / `sqlite3` / `zipfile` / `tomllib` / `zoneinfo` / `logging` のみを使う。
pip も venv も nix も不要。

## セットアップ

```bash
cp config/secrets.env.example config/secrets.env
chmod 600 config/secrets.env
# エディタで API キーを記入する
```

## 設定

閾値は例外なく `config/config.toml` にある。**コードに数値リテラルは置かない。**
この規則は機械的に検査される:

```bash
python3 tools/check_config.py
```

設定の内容を一覧表示し、内部矛盾を検証し、`src/daytrade/` に残った数値リテラルを走査する。
仕様書から変更した値には `[変更]`、解釈が未確定の箇所には `[要判断]` のコメントが付いている。

検証器は起動時にも走る。以下のような矛盾はプロセスが立ち上がる前に落ちる。

- `stops.ratchet_only_up = false`（トレール線が下がり建値割れが起きる）
- `schedule.force_exit` がクロージング・オークション開始以降
- `schedule.daily_report` が大引けより前
- `freshness.quote_max_age_sec` が `polling.quote_interval_sec` 以下（正常時も鮮度違反になる）
- `layer1.tick_continuity_min_ok_bars` が窓の本数を超える（永久に成立しない）

## テスト

```bash
python3 -m unittest discover -s tests -v
```

通信もJ-Quantsのアドオン課金も不要。株探の生レスポンスと J-Quants の正解データを
`tests/fixtures/` に固定してあるので、**株探のHTML/CSV構造が変わったときにここが最初に落ちる**。

## 判定層の約束

- 全て純関数。同じ入力に必ず同じ結果を返す
- **現在時刻は引数 `now` として受け取る。内部で時計を読まない**
  （9:45 のATR倍率切り替えがあるため、内部で時刻を見るとバックテストで再現できない）
- 1分足の供給元は `sources/barsource.py` で抽象化してある。
  株探の1分足でも、累計値からの再構成でも、保存済みデータでも、判定側は区別しない

## 構成

```
config/
  config.toml          全閾値。コードに数値を置かない
  secrets.env          認証情報（.gitignore 済み）
src/daytrade/
  config.py            設定の読み込みと起動時検証
  clock.py             JST・立会時間・昼休みを除いた経過分
  models.py            ドメイン型（Bar / Quote / 状態機械 / 決済理由）
  errors.py            例外。失敗を None で表現しない
  freshness.py         ★データ鮮度ガード★
  logging_setup.py     通常ログ + 判定ジャーナル + 取引ジャーナル
  sources/             データ取得層（J-Quants / 株探）
  engine/              判定層（純関数。本番とバックテストで共有）
  state/               状態管理層（ポジションの状態機械）
  notify/              通知層（Slack）
  batch/               前日バッチ
tools/check_config.py  設定検証 + マジックナンバー走査
data/journal/          判定・取引・取得のJSONLジャーナル
```

層は分離されている。**株探のHTML構造が変わってもパーサの差し替えだけで済む。**
判定層は純関数で書かれ、同じ入力に同じ結果を返す（バックテストと本番で同じコードを使うため）。

## データ鮮度ガード

このシステムで最も重要な部品。「古い値を掴んだまま判定を走らせない」を機械的に担保する。

- 全ての価格データは `as_of`（データ源が示す時刻）を持つ。`fetched_at` ではなく `as_of` で
  測る。取得は成功したが中身が10分前、という最も危険な壊れ方は `fetched_at` では検出できない
- 規定秒数を超えたら `StaleDataError` を投げる。戻り値 `None` ではない。
  握りつぶすには `except` を書く必要があり、レビューで見つかる
- 未来の `as_of` も拒否する。時計ずれで鮮度ガード自体が無力化されるのを防ぐ
- 連続失敗を数え、閾値を超えたら当該銘柄の判定を停止し `#system` へ通知する

判定側は必ず `FreshnessGuard.require_fresh()` を通す。生のデータを判定に渡す経路は作らない。

## データソース

| 層 | 用途 | ソース |
|---|---|---|
| 前日バッチ（第0層） | 貸借区分・信用規制・日足・ATR・ILLIQ・時価総額 | J-Quants V2 |
| 当日リアルタイム | 現在値・VWAP・累計売買代金・1分足 | 株探 |
| バックテスト | 分足2年 / 日足20年 | J-Quants V2 |

J-Quants は日中配信がない（全て16:30頃更新）ため、リアルタイム層は株探でしか代替できない。
逆に前日バッチは J-Quants が圧倒的に効率的（全4,444銘柄が1リクエスト）。
接続方法と実測値は [`docs/00_recon.md`](docs/00_recon.md) に記録してある。
