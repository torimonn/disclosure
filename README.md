# 貸借対照表自動抽出ツール README

## 概要

本ツールは、Google Generative AI（Gemini）を用いてPDF形式のディスクロージャー資料から「貸借対照表（Balance Sheet）」および「損益計算書（Income Statement）」を自動抽出し、CSVファイルとして出力するPythonスクリプトです。複数のPDFをまとめて処理することもできます。

主な流れは以下のとおりです：

1. ユーザーがPDFファイルをアップロード
2. Google Generative AI にPDFを渡し、メタデータ（会社名・貸借対照表掲載ページ番号・表の種類・貸借対照表の金額単位・損益計算書の金額単位）を抽出
3. 同じPDFを再度渡し、貸借対照表そのものの構造化データを抽出
4. 同様に損益計算書のデータも抽出
5. 取得したJSONデータをPydanticモデルで検証・パース
6. 各表の金額単位に基づいて数値を補正し、貸借対照表→損益計算書の順に一列へまとめ
   つつ2列目の3行目に貸借対照表ページ、4行目に損益計算書ページを記録したCSVを生成
7. 複数PDFを指定した場合は順に処理し、各PDFごとに1つのCSVを保存

## 前提条件

- Python 3.8 以上
- Google Colab またはローカル環境で実行可能
- Google Generative AI（Gemini）APIキーを発行済み
- Pydantic、pypdf、google-genai、pandas がインストールされていること

## セットアップ方法

### 1. ライブラリのインストール

以下のコマンドを実行して、必要なライブラリをインストールします。
Colab 環境であれば、セルの先頭に `!` を付けて実行してください。

```bash
pip install -qU google-genai pydantic pypdf pandas
```

### 2. APIキーの準備

Google Generative AI（Gemini）を利用するには、Google Cloud Console でプロジェクトを作成し、APIキーを発行しておく必要があります。

- Colab を利用する場合は、Notebook 画面左側の「Secrets（🔒）」アイコンをクリックし、`GOOGLE_API_KEY` という名前でキーを登録してください。
- ローカル環境で実行する場合は、環境変数 `GOOGLE_API_KEY` にAPIキーを設定するか、適宜コード内で直接指定します（非推奨）。

### 3. モデル名を確認

スクリプト内の `MODEL_NAME` には、利用可能な最新モデル名（例:`gemini-2.5-flash-preview-05-20`）を指定してください。

実行前に以下のコードを使って、サポートされているモデル名一覧を確認してください：

```python
import google.generativeai as genai

# すでに genai.configure(api_key=...) を済ませた上で実行
models = genai.GenerativeModel.list_models()
for m in models:
    print(f"モデル名: {m.name}, サポートメソッド: {m.supported_methods}")
```

上記出力の中から、`generateContent` がサポートされているモデル名をスクリプト中の `model_name` に指定してください。

## ファイル構成

- `README.md` - 本リードミー
- `main_extraction.py`（任意のファイル名） - メタデータ抽出 → 貸借対照表抽出 → CSV出力 → ダウンロード までの全処理をまとめた Python スクリプト
- `main_extraction.ipynb` - Colab 上で実行しやすいノートブック形式のサンプル
- `requirements.txt`（任意）

```
google-genai
pydantic
pypdf
pandas
```

## 使い方

### 1. スクリプトを開く・編集

スクリプト冒頭のライブラリインストール部分や、モデル名を確認して適宜編集してください。

```python
# 例: 利用モデル名を指定
MODEL_NAME = "gemini-2.5-flash-preview-05-20"
```

### 2. Colab 環境で実行する場合

ノートブック `main_extraction.ipynb` を開き、上から順に以下のセルを実行します。

1. **ライブラリのインストール**：`pip install` セルで必要パッケージを準備
2. **API キー設定**：`google.colab.userdata` から `GOOGLE_API_KEY` を読み込み `genai.configure` を実行
3. **PDF アップロード**：`files.upload()` セルで処理したい PDF を選択
4. **処理実行**：最後のセルを実行すると、各 PDF からメタデータと財務諸表を抽出して CSV がダウンロードされます

### 3. ローカル環境で実行する場合

1. ターミナルを開き、仮想環境（推奨）をアクティベートします
2. 必要なライブラリをインストール：
   ```bash
   pip install -r requirements.txt
   ```
3. 環境変数として APIキーを設定する：
   ```bash
   export GOOGLE_API_KEY="YOUR_API_KEY_HERE"
   ```
   Windows の場合は `set GOOGLE_API_KEY=YOUR_API_KEY_HERE`
4. スクリプトを実行：
   ```bash
   python main_extraction.py your1.pdf your2.pdf
   ```

## スクリプトの流れ詳細

### 1. アップロード処理

- **Colab**：`google.colab.files.upload()` でPDFを選択
- **ローカル**：スクリプト実行時の引数として PDF パスを渡す

### 2. PDFメタデータ抽出

- 関数 `upload_pdf_to_genai(pdf_file_path)` で PDF を Google Generative AI サービスにアップロード
- `create_generative_content_parts_for_metadata()` で LLM 指示文とファイルをまとめ、`call_llm_for_structured_output(..., output_model=PDFMetadata)` で実行
- `PDFMetadata` モデルにマッチしていれば成功し、会社名・貸借対照表掲載ページ番号・表の種類・貸借対照表の金額単位(`balance_sheet_amount_unit`)・損益計算書の金額単位(`income_statement_amount_unit`)を取得

### 3. 貸借対照表抽出

- メタデータで得た会社名を引数に `create_generative_content_parts_for_balance_sheet()` で貸借対照表抽出用の指示文を作成
- 再度 PDF をアップロードし、`call_llm_for_structured_output(..., output_model=BalanceSheetResponse)` で実行
- 取得した JSON を `BalanceSheetResponse` モデルで検証・パースし、`fiscal_year_data` 配列を取り出す

### 4. CSV 出力＆ダウンロード

`build_financial_rows()` で取り出した行データを DataFrame にまとめ、`financials.csv` として保存します。複数PDFを指定した場合も 1 つの CSV に連結されます。
出力は2列（科目、金額(円)）で、1 行目には会社名、2 行目には決算期、続けてページ番号や明細が並びます。
Colab 上では `files.download()` を利用すればブラウザからダウンロードできます。

### 5. クリーンアップ

- 各アップロード用に作成された一時ファイルを `genai.delete_file(...)` で削除
- ローカルの PDF（`/content/`など）を `os.remove(...)` で削除

## 注意点

### 1. モデルの互換性

使用するモデル名は必ず `list_models()` で確認してください。
もし `generateContent` をサポートしていないモデルを指定すると、HTTP 404 エラーになります。

### 2. PDF の構造・品質

PDF のレイアウトによっては、LLM が正しくテーブル構造を認識できないことがあります。特にスキャン・画像化されたPDFは精度が落ちる可能性があります。
必要に応じて、PyPDF で補助的にテキストを抽出して指示文に含める機能を有効化していますが、必須ではありません。

### 3. CSV フォーマット

- 1 行目：「金庫名」に会社名を記録
- 2 行目：「決算期」に会計年度末日（YYYY-MM-DD）を記録
- 3 行目：「貸借対照表記載ページ」にページ番号（カンマ区切り）を記録
- 4 行目：「損益計算書記載ページ」にページ番号（カンマ区切り）を記録
- 5 行目以降：勘定科目名と金額(円)を順番に並べます
- 金額は `balance_sheet_amount_unit` や `income_statement_amount_unit` で補正した後の値を保存します。値が `null` の場合は空欄となります
- 例として「(単位：百万円)」とある場合は 1,000,000 倍して円換算した金額が出力されます

## トラブルシューティング

### 「404 … model is not found」エラー

→ 指定モデル名が誤っているか、サポート外のバージョンを指定しています。`list_models()` で再確認してください。

### Pydantic バリデーションエラー

→ LLM の返す JSON 構造と Pydantic モデルの定義が合致していません。README で示したクラス（`BalanceSheetResponse`, `BalanceSheetBody`, `FiscalYearBalanceSheet` など）がスキーマに合っているか確認し、必要に応じて調整してください。

### CSV が生成できない / ダウンロードが始まらない

- Colab 環境以外では `files.download()` は機能しません。ローカル実行時は手動で `financials.csv` を取得してください
- 保存先ディレクトリが存在しない場合は、スクリプト中の出力パス(`financials.csv`)を変更してください

### PDF アップロード／削除でエラーが出る

- Colab のファイルパス（`/content/`）を正しく指定しているか確認
- `genai.delete_file(...)` が失敗しても、ローカルの一時ファイルは手動で削除可能です

## カスタマイズ例

### 特定の会計年度だけを抽出したい

`balance_sheet_resp.balance_sheet.fiscal_year_data` は配列形式なので、たとえば 2 番目の年度を抽出したい場合は `fiscal_year_data[1]` を参照してください。そのうえで CSV 出力関数を修正し、"最新" ではなく任意のインデックスを使うようにできます。

### 子項目のインデントを可視化したい

`build_financial_rows()` 内のフラット化処理を変更し、勘定科目名の前にスペースを挿入することでインデントを表現できます（例：`" " * item.indent_level + item.name_japanese`）。

### 英語名カラムを追加したい

`build_financial_rows()` で取得した行データを加工し、列数を増やした DataFrame を作成すれば、CSV に英語名カラムを追加できます。

### 複数の CSV を横に連結したい

`merge_financials.py` は、個別に生成した `financials.csv` を勘定科目で突き合わせ、
横方向に並べ替えるための補助スクリプトです。各 CSV は本 README の "CSV フォーマッ
ト" 節で説明した構成を想定しており、先頭 4 行のメタ情報を除いた 5 行目以降の
`科目` と `金額(円)` を利用して結合します。

次のように複数ファイルを引数に指定して実行してください。

```bash
python merge_financials.py 信金A.csv 信金B.csv 信金C.csv
```

実行すると `merged_financials.csv` が生成され、1 列目に勘定科目、2 列目以降には各金
庫名を列見出しとした金額が並びます。科目が一致しない場合は外部結合となるため、当
該金庫にその科目が存在しなければ空欄（null）が入ります。

## ライセンス・著作権

本リポジトリはオープンソースとして提供されており、特に制限がない場合は自由に改変・再配布して構いません。ただし、Google Generative AI の利用規約および関連ライブラリのライセンス条項を遵守してください。
