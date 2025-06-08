import os
import json
import sys
from datetime import date
from typing import List, Optional, Union

import google.generativeai as genai
from pydantic import BaseModel, Field, ValidationError
from pypdf import PdfReader
import pandas as pd

MODEL_NAME = "gemini-2.5-flash-preview-05-20"

class PDFMetadata(BaseModel):
    """PDFから抽出するメタデータ。貸借対照表と損益計算書で金額単位を別々に保持"""
    company_name_japanese: str = Field(description="会社名（日本語）")
    company_name_english: Optional[str] = Field(default=None, description="会社名（英語）")
    balance_sheet_pages_1_indexed: List[int] = Field(description="貸借対照表ページ番号リスト")
    income_statement_pages_1_indexed: Optional[List[int]] = Field(default=None, description="損益計算書ページ番号リスト")
    estimated_balance_sheet_type: Optional[str] = Field(default=None, description="貸借対照表の種類推定")
    estimated_income_statement_type: Optional[str] = Field(default=None, description="損益計算書の種類推定")
    balance_sheet_amount_unit: int = Field(description="貸借対照表の金額単位。百万円なら1000000等")
    income_statement_amount_unit: Optional[int] = Field(default=None, description="損益計算書の金額単位。百万円なら1000000等")

class StatementItem(BaseModel):
    name_japanese: str
    name_english: str
    value: Optional[Union[int, float]]
    indent_level: int
    children: List['StatementItem'] = Field(default_factory=list)

# Pydantic v2 では update_forward_refs() の代わりに model_rebuild() を使用
StatementItem.model_rebuild()

class Section(BaseModel):
    total_value: Optional[Union[int, float]] = None
    items: List[StatementItem]

class FiscalYearBalanceSheet(BaseModel):
    end_date: date
    description: Optional[str] = None
    assets: Section
    liabilities: Section
    net_assets: Section

class BalanceSheetBody(BaseModel):
    fiscal_year_data: List[FiscalYearBalanceSheet]

class BalanceSheetResponse(BaseModel):
    balance_sheet: BalanceSheetBody

class FiscalYearIncomeStatement(BaseModel):
    end_date: date
    description: Optional[str] = None
    items: List[StatementItem]

class IncomeStatementBody(BaseModel):
    fiscal_year_data: List[FiscalYearIncomeStatement]

class IncomeStatementResponse(BaseModel):
    income_statement: IncomeStatementBody

def upload_pdf_to_genai(pdf_file_path: str) -> Optional[genai.protos.FileData]:
    try:
        return genai.upload_file(pdf_file_path)
    except Exception as e:
        print(f"PDFのアップロードに失敗しました: {e}")
        return None

def extract_text_from_pdf_pypdf(pdf_file_path: str, pages_0_indexed: Optional[List[int]]) -> str:
    try:
        reader = PdfReader(pdf_file_path)
        if pages_0_indexed is None:
            pages = range(len(reader.pages))
        else:
            pages = pages_0_indexed
        texts = [reader.pages[p].extract_text() or "" for p in pages]
        return "\n".join(texts)
    except Exception as e:
        print(f"PDFテキスト抽出に失敗しました: {e}")
        return ""

def create_generative_content_parts_for_metadata(uploaded_pdf_file: genai.protos.FileData, pydantic_schema: dict) -> List[Union[str, genai.protos.FileData]]:
    schema_json = json.dumps(pydantic_schema, ensure_ascii=False, indent=2)
    instruction = (
        "PDF から会社名、貸借対照表ページ、損益計算書ページ、表の種類、" 
        "貸借対照表用の金額単位、損益計算書用の金額単位を抽出してください。" 
        "出力はJSONのみで、スキーマは次の通りです:\n" + schema_json
    )
    return [instruction, uploaded_pdf_file]

def create_generative_content_parts_for_balance_sheet(uploaded_pdf_file: genai.protos.FileData, company_name_japanese: str, company_name_english: str, pydantic_schema: dict, auxiliary_pdf_text: Optional[str] = None) -> List[Union[str, genai.protos.FileData]]:
    schema_json = json.dumps(pydantic_schema, ensure_ascii=False, indent=2)
    instruction = f"""会社名「{company_name_japanese} ({company_name_english})」の単体貸借対照表を抽出し、次のJSONスキーマに従ってください:\n{schema_json}"""
    parts = [instruction, uploaded_pdf_file]
    if auxiliary_pdf_text:
        parts.append("\n\n### 補助テキスト:\n" + auxiliary_pdf_text)
    return parts

def create_generative_content_parts_for_income_statement(uploaded_pdf_file: genai.protos.FileData, company_name_japanese: str, company_name_english: str, pydantic_schema: dict, auxiliary_pdf_text: Optional[str] = None) -> List[Union[str, genai.protos.FileData]]:
    schema_json = json.dumps(pydantic_schema, ensure_ascii=False, indent=2)
    instruction = f"""会社名「{company_name_japanese} ({company_name_english})」の単体損益計算書を抽出し、次のJSONスキーマに従ってください:\n{schema_json}"""
    parts = [instruction, uploaded_pdf_file]
    if auxiliary_pdf_text:
        parts.append("\n\n### 補助テキスト:\n" + auxiliary_pdf_text)
    return parts

def call_llm_for_structured_output(content_parts: List[Union[str, genai.protos.FileData]], output_model: BaseModel) -> Optional[BaseModel]:
    try:
        model = genai.GenerativeModel(model_name=MODEL_NAME)
        response = model.generate_content(
            contents=content_parts,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0
            ),
            safety_settings={
                'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE',
                'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE',
                'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE',
                'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE',
            }
        )
        text = response.text.strip()
        if text.startswith("```json") and text.endswith("```"):
            text = text[7:-3].strip()
        data = json.loads(text)
        return output_model.model_validate(data)
    except (ValidationError, json.JSONDecodeError) as e:
        print("LLM応答の解析に失敗しました", e)
        print(text)
        return None
    except Exception as e:
        print("LLM呼び出しに失敗しました", e)
        return None

def multiply_unit(items: List[StatementItem], amount_unit: int):
    for it in items:
        if it.value is not None:
            it.value *= amount_unit
        if it.children:
            multiply_unit(it.children, amount_unit)

def export_financials_to_csv(
    balance_sheet_resp: BalanceSheetResponse,
    income_statement_resp: IncomeStatementResponse,
    company_name: str,
    bs_unit: int,
    pl_unit: int,
    bs_pages: Optional[List[int]],
    pl_pages: Optional[List[int]],
    output_path: str,
):
    latest_bs = balance_sheet_resp.balance_sheet.fiscal_year_data[0]
    latest_pl = income_statement_resp.income_statement.fiscal_year_data[0]

    multiply_unit(latest_bs.assets.items, bs_unit)
    multiply_unit(latest_bs.liabilities.items, bs_unit)
    multiply_unit(latest_bs.net_assets.items, bs_unit)
    multiply_unit(latest_pl.items, pl_unit)

    bs_pages_str = ",".join(str(p) for p in bs_pages) if bs_pages else ""
    pl_pages_str = ",".join(str(p) for p in pl_pages) if pl_pages else ""

    rows = []
    # 1 行目: 会社名
    rows.append(("", company_name))
    # 2 行目: 会計年度末日
    rows.append(("", latest_bs.end_date.strftime("%Y-%m-%d")))
    # 3 行目: 貸借対照表ページ番号
    rows.append(("", bs_pages_str))
    # 4 行目: 損益計算書ページ番号
    rows.append(("", pl_pages_str))

    def flatten(items, dst):
        for it in items:
            dst.append((it.name_japanese, it.value if it.value is not None else ""))
            if it.children:
                flatten(it.children, dst)

    rows.append(("-- 貸借対照表 --", ""))
    flatten(latest_bs.assets.items, rows)
    flatten(latest_bs.liabilities.items, rows)
    flatten(latest_bs.net_assets.items, rows)

    rows.append(("", ""))
    rows.append(("-- 損益計算書 --", ""))
    flatten(latest_pl.items, rows)

    df = pd.DataFrame(rows, columns=["科目", "金額(円)"])
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"CSVを保存しました: {output_path}")

def process_pdf(pdf_path: str):
    print(f"処理開始: {pdf_path}")
    uploaded = upload_pdf_to_genai(pdf_path)
    if not uploaded:
        return
    schema_meta = PDFMetadata.model_json_schema()
    meta_parts = create_generative_content_parts_for_metadata(uploaded, schema_meta)
    metadata: Optional[PDFMetadata] = call_llm_for_structured_output(meta_parts, PDFMetadata)
    try:
        genai.delete_file(uploaded.name)
    except Exception:
        pass
    if not metadata:
        print("メタデータの取得に失敗しました")
        return

    company_jp = metadata.company_name_japanese
    company_en = metadata.company_name_english or company_jp
    bs_unit = metadata.balance_sheet_amount_unit
    pl_unit = metadata.income_statement_amount_unit or bs_unit

    pages_bs_list = metadata.balance_sheet_pages_1_indexed or []
    pages_pl_list = metadata.income_statement_pages_1_indexed or []

    pages_bs = [p - 1 for p in pages_bs_list] if pages_bs_list else None
    pages_pl = [p - 1 for p in pages_pl_list] if pages_pl_list else None

    # Balance Sheet
    uploaded_bs = upload_pdf_to_genai(pdf_path)
    aux_text_bs = extract_text_from_pdf_pypdf(pdf_path, pages_bs)
    schema_bs = BalanceSheetResponse.model_json_schema()
    parts_bs = create_generative_content_parts_for_balance_sheet(uploaded_bs, company_jp, company_en, schema_bs, aux_text_bs)
    bs_resp: Optional[BalanceSheetResponse] = call_llm_for_structured_output(parts_bs, BalanceSheetResponse)
    try:
        genai.delete_file(uploaded_bs.name)
    except Exception:
        pass
    if not bs_resp:
        print("貸借対照表の取得に失敗しました")
        return

    # Income Statement
    uploaded_pl = upload_pdf_to_genai(pdf_path)
    aux_text_pl = extract_text_from_pdf_pypdf(pdf_path, pages_pl)
    schema_pl = IncomeStatementResponse.model_json_schema()
    parts_pl = create_generative_content_parts_for_income_statement(uploaded_pl, company_jp, company_en, schema_pl, aux_text_pl)
    pl_resp: Optional[IncomeStatementResponse] = call_llm_for_structured_output(parts_pl, IncomeStatementResponse)
    try:
        genai.delete_file(uploaded_pl.name)
    except Exception:
        pass
    if not pl_resp:
        print("損益計算書の取得に失敗しました")
        return

    output_csv = os.path.splitext(os.path.basename(pdf_path))[0] + ".csv"
    export_financials_to_csv(
        bs_resp,
        pl_resp,
        company_jp,
        bs_unit,
        pl_unit,
        pages_bs_list,
        pages_pl_list,
        output_csv,
    )


def main():
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("環境変数 GOOGLE_API_KEY を設定してください")
        return
    genai.configure(api_key=api_key)

    if len(sys.argv) < 2:
        print("PDFファイルを指定してください")
        return
    for pdf_path in sys.argv[1:]:
        process_pdf(pdf_path)

if __name__ == "__main__":
    main()
