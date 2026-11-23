# Limit Desk

Claude Code、Codex、Gemini / Antigravity CLI の利用枠を一画面で確認できるローカルダッシュボードです。利用率とリセット時刻のほか、Claude Code の残り利用枠の履歴や、ローカルログから集計したトークン消費の内訳も表示します。

## 起動

Windows PowerShell と Python 3.10 以降を想定しています。追加の Python パッケージは不要です。クローンしたフォルダで次を実行し、ブラウザーで `http://127.0.0.1:8765` を開きます。

```powershell
.\start.ps1
# PowerShell スクリプトを実行できない場合
python server.py
```

Claude Code と Antigravity CLI の statusLine を接続するには、通常の PowerShell で次を実行し、対象の CLI を再起動します。

```powershell
.\start.ps1 -ConnectCli
# 接続設定だけを行う場合
python connect_cli.py
```

接続スクリプトは変更前の設定をバックアップし、設定済みの statusLine を保持します。既存の statusLine から連携する場合は、受け取った JSON を標準入力で `statusline.py` に渡します。第1引数は Claude Code なら `claude`、Antigravity CLI なら `gemini` です。別の作業ディレクトリから呼ぶ場合は、Python とスクリプトに絶対パスを指定します。

## データの取得と表示

| サービス | 主な取得経路 | 代替経路 |
| --- | --- | --- |
| Codex | App Server の利用枠 API | セッションに記録された利用枠 |
| Claude Code | statusLine | 既存の CLI 認証による利用枠 API |
| Gemini / Antigravity CLI | Antigravity CLI の statusLine | 従来の Gemini CLI の認証による Code Assist の利用枠取得 |

- 取得時刻や利用枠を取得できない理由を表示します。ダッシュボードは取得結果を60秒間キャッシュします。
- Claude Code の利用枠履歴は statusLine の観測値を SQLite に保存します。リセットをまたぐ区間や10分を超える欠測区間はグラフ上で途切れます。
- Claude Code の消費内訳はローカルログをメッセージ ID で重複排除して集計します。利用枠とトークン数は別々に表示します。
- 接続時の記録と履歴は `.local/` に保存します。サーバーはループバックアドレスで待ち受け、認証情報や会話本文をブラウザーへ送信しません。
- 代替 API の動作はサービス側の仕様に依存します。取得できる項目は CLI のバージョンや契約プランによって異なります。

## Windows のアプリウィンドウとスマホ閲覧

- `pythonw launch.pyw` を実行すると、必要に応じてサーバーを起動し、Microsoft Edge のアプリモードで開きます。
- PC とスマホで同じアカウントの Tailscale に接続し、PC で `.\start-mobile.ps1` を実行すると、表示された HTTPS URL から閲覧できます。停止は `.\start-mobile.ps1 -Stop` です。

## テスト

```powershell
python -m unittest discover -v
node test_ui.js
```

Python のテストは取得処理、履歴、集計、接続設定を確認します。Node.js のテストは利用枠を受け取ったときの画面表示を確認します。
