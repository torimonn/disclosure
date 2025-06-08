import pandas as pd
import sys
from typing import List


def read_financial_csv(path: str) -> pd.DataFrame:
    """金融機関ごとの縦持ちCSVを読み込み、
    勘定科目列をキーに横持ち用のDataFrameを返す。

    先頭4行はメタ情報として扱い、5行目以降を勘定科目と金額とみなす。
    2列目に記録された金庫名を新しい列名として利用する。
    """
    df = pd.read_csv(path)
    if df.empty or df.shape[1] < 2:
        raise ValueError(f"CSV format error: {path}")

    # 2列目1行目が金庫名
    column_name = df.iloc[0, 1]

    # 5行目以降が勘定科目データ
    data = df.iloc[4:].copy().reset_index(drop=True)
    data.rename(columns={'金額(円)': column_name}, inplace=True)
    return data


def merge_csvs(paths: List[str]) -> pd.DataFrame:
    """複数の縦持ちCSVを勘定科目で外部結合して横持ち形式に変換する。"""
    merged: pd.DataFrame | None = None
    for p in paths:
        df = read_financial_csv(p)
        if merged is None:
            merged = df
        else:
            merged = pd.merge(merged, df, on='科目', how='outer')
    return merged


def main():
    if len(sys.argv) < 2:
        print('CSVファイルを指定してください')
        return
    paths = sys.argv[1:]
    merged = merge_csvs(paths)
    merged.to_csv('merged_financials.csv', index=False, encoding='utf-8-sig')
    print('CSVを保存しました: merged_financials.csv')


if __name__ == '__main__':
    main()
