# デイトレード分析ダッシュボード

日本株の主要約150銘柄を毎日スクリーニングし、VWAPと値動きの複数銘柄チャート、
セクター資金フロー、9:30VWAP vs 終値の記録(高値終い率・日経連動度)を
1枚のHTMLダッシュボードに自動生成します。

- 平日15:45(JST)にGitHub Actionsが自動実行
- ダッシュボード: `https://<ユーザー名>.github.io/<リポジトリ名>/`
- 記録は `records.csv`(銘柄別)と `market.csv`(日経)に毎日蓄積

## セットアップ手順(初回のみ)

1. GitHubで新規リポジトリを作成(Public)
2. このフォルダの中身を全部リポジトリにアップロード
   - `workflow-update.yml` は **`.github/workflows/update.yml`** にリネームして配置すること
3. リポジトリの Settings → Pages → Source: 「Deploy from a branch」、
   Branch: `main` / フォルダ: `/docs` を選択して Save
4. Actions タブ → 「update-dashboard」→「Run workflow」で初回手動実行
5. 数分後 `https://<ユーザー名>.github.io/<リポジトリ名>/` でダッシュボードが見られる

## ファイル構成

| ファイル | 役割 |
|---|---|
| run.py | メイン処理(取得→分析→HTML生成→記録追記) |
| template.html | ダッシュボードのテンプレート |
| universe.csv | スクリーニング母集団(約150銘柄) |
| watchlist.csv | 常時表示銘柄(★) |
| config.json | 表示数・フィルタ初期値 |
| records.csv | 9:30VWAP vs 終値の日次記録(自動蓄積) |
| market.csv | 日経225の9:30→引け方向(自動蓄積) |
| backfill.py | 過去60日分の記録一括投入(初回済み・通常は不要) |

## 注意

- データはyfinance(Yahoo Finance非公式)・約20分遅延。仕様変更で動かなくなるリスクあり
- 本ツールは分析補助であり、投資判断は自己責任
