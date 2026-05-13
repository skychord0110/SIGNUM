"""
build_universe.py
=================
JPX 公式の「東証上場銘柄一覧 (data_j.xls)」をダウンロードして universe.csv を再生成。
"""
from __future__ import annotations

# Windows コンソール cp932 対策
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import argparse
import io
import traceback
from pathlib import Path


def safe_print(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        try:
            print(msg.encode("ascii", "replace").decode("ascii"))
        except Exception:
            pass


def preflight() -> list[str]:
    issues: list[str] = []
    try:
        import pandas  # noqa: F401
    except ImportError:
        issues.append("pandas が未インストール - pip install pandas")
    try:
        import requests  # noqa: F401
    except ImportError:
        issues.append("requests が未インストール - pip install requests")
    has_xlrd = False
    try:
        import xlrd  # noqa: F401
        has_xlrd = True
    except ImportError:
        pass
    has_calamine = False
    try:
        import python_calamine  # noqa: F401
        has_calamine = True
    except ImportError:
        pass
    if not (has_xlrd or has_calamine):
        issues.append(
            "xlrd と python-calamine の両方とも未インストール。\n"
            "  推奨: pip install \"xlrd==1.2.0\""
        )
    return issues


JPX_URLS = [
    "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls",
    "http://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls",
]

SECTOR_TO_THEME = {
    "情報・通信業": "DX・SaaS", "サービス業": "サービス",
    "小売業": "内需・ディフェンシブ", "卸売業": "内需・ディフェンシブ",
    "陸運業": "EC・物流", "海運業": "内需・ディフェンシブ",
    "空運業": "インバウンド", "倉庫・運輸関連業": "EC・物流",
    "電気機器": "半導体関連", "機械": "ロボット・FA",
    "輸送用機器": "内需・ディフェンシブ", "精密機器": "半導体関連",
    "金属製品": "内需・ディフェンシブ", "鉄鋼": "内需・ディフェンシブ",
    "非鉄金属": "内需・ディフェンシブ", "ガラス・土石製品": "内需・ディフェンシブ",
    "ゴム製品": "内需・ディフェンシブ", "繊維製品": "内需・ディフェンシブ",
    "パルプ・紙": "内需・ディフェンシブ", "化学": "半導体関連",
    "石油・石炭製品": "内需・ディフェンシブ", "医薬品": "バイオ・医療",
    "食料品": "内需・ディフェンシブ", "水産・農林業": "内需・ディフェンシブ",
    "鉱業": "内需・ディフェンシブ", "建設業": "内需・ディフェンシブ",
    "電気・ガス業": "環境・再エネ", "不動産業": "内需・ディフェンシブ",
    "銀行業": "内需・ディフェンシブ", "証券、商品先物取引業": "フィンテック・暗号資産",
    "保険業": "内需・ディフェンシブ", "その他金融業": "フィンテック・暗号資産",
    "その他製品": "ゲーム・エンタメ",
}


def download_jpx_xls() -> bytes:
    import requests
    last_error = None
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
    }
    for url in JPX_URLS:
        safe_print("[DL] JPX から取得中: " + url)
        try:
            r = requests.get(url, timeout=60, headers=headers)
            r.raise_for_status()
            ctype = r.headers.get("Content-Type", "")
            if "html" in ctype.lower() or r.content[:6].startswith(b"<!DOCT") or r.content[:5].startswith(b"<html"):
                raise RuntimeError(
                    "JPX が HTML を返しました (Content-Type: " + ctype + ")。"
                    "プロキシ/VPN/会社ファイアウォールをご確認ください。"
                )
            safe_print("[OK] ダウンロード成功 (" + format(len(r.content), ",") + " bytes)")
            return r.content
        except Exception as e:
            last_error = e
            safe_print("  [X] 失敗: " + str(e))
            continue
    raise RuntimeError("JPX への接続に失敗。最後のエラー: " + str(last_error))


def _parse_with_xlrd_direct(content: bytes):
    import xlrd
    import pandas as pd
    book = xlrd.open_workbook(file_contents=content)
    sheet = book.sheet_by_index(0)
    rows = []
    for r in range(sheet.nrows):
        row_data = []
        for c in range(sheet.ncols):
            v = sheet.cell_value(r, c)
            if isinstance(v, float) and v.is_integer():
                v = int(v)
            row_data.append(v)
        rows.append(row_data)
    if not rows:
        return pd.DataFrame()
    header = [str(h) for h in rows[0]]
    df = pd.DataFrame(rows[1:], columns=header)
    return df


def _parse_with_calamine(content: bytes):
    from python_calamine import CalamineWorkbook
    import pandas as pd
    wb = CalamineWorkbook.from_filelike(io.BytesIO(content))
    sheet = wb.get_sheet_by_index(0)
    data = sheet.to_python()
    if not data:
        return pd.DataFrame()
    header = [str(h) for h in data[0]]
    df = pd.DataFrame(data[1:], columns=header)
    return df


def _parse_with_pandas(content: bytes, engine):
    import pandas as pd
    if engine is None:
        return pd.read_excel(io.BytesIO(content))
    return pd.read_excel(io.BytesIO(content), engine=engine)


def parse_jpx_xls(content: bytes):
    attempts = [
        ("xlrd direct (1.2.0)", _parse_with_xlrd_direct),
        ("python-calamine", _parse_with_calamine),
        ("pandas (engine=xlrd)", lambda c: _parse_with_pandas(c, "xlrd")),
        ("pandas (engine=calamine)", lambda c: _parse_with_pandas(c, "calamine")),
        ("pandas (engine=auto)", lambda c: _parse_with_pandas(c, None)),
    ]
    errors: list[str] = []
    for name, fn in attempts:
        try:
            df = fn(content)
            safe_print("[OK] パース成功: " + name)
            return df
        except Exception as e:
            errors.append(name + ": " + str(e))
            continue
    msg = "\n  ".join(errors)
    raise RuntimeError("全てのパース方法が失敗しました:\n  " + msg)


def normalise_market(raw: str) -> str:
    raw = str(raw)
    if "プライム" in raw:
        return "Prime"
    if "スタンダード" in raw:
        return "Standard"
    if "グロース" in raw:
        return "Growth"
    if "PRO" in raw:
        return "PRO"
    return "Other"


def build(keep_themes: bool = True, exclude_etf: bool = True):
    import pandas as pd

    content = download_jpx_xls()
    df = parse_jpx_xls(content)
    safe_print("[OK] DataFrame 取得 (" + format(len(df), ",") + " 行 x " + str(len(df.columns)) + " 列)")
    safe_print("  列: " + str(list(df.columns)) + "")

    # ★重要★ 完全一致でリネーム (部分一致だと "33業種コード" 等まで code にされて重複)
    rename = {}
    for c in df.columns:
        cs = str(c).strip()
        if cs == "コード":
            rename[c] = "code"
        elif cs == "銘柄名":
            rename[c] = "name"
        elif cs in ("市場・商品区分", "市場区分"):
            rename[c] = "market_raw"
        elif cs == "33業種区分":
            rename[c] = "sector"
    df = df.rename(columns=rename)

    # 重複列が万一できていたら最初のものだけ残す
    df = df.loc[:, ~df.columns.duplicated()]

    if "code" not in df.columns:
        raise RuntimeError(
            "JPX ファイルに『コード』列が見つかりません。フォーマット変更の可能性。\n"
            "  検出列: " + str(list(df.columns))
        )

    keep = [c for c in ["code", "name", "market_raw", "sector"] if c in df.columns]
    df = df[keep].copy()

    # code 列を文字列化 -> 数値も「7203.0」になるので前処理
    code_series = df["code"]
    # まれに DataFrame で来る場合の保険
    if isinstance(code_series, pd.DataFrame):
        code_series = code_series.iloc[:, 0]
    df["code"] = (
        code_series.astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.strip()
    )
    before = len(df)
    df = df[df["code"].str.match(r"^\d{4}$", na=False)]
    safe_print("[OK] 4桁コード絞り込み: " + format(before, ",") + " -> " + format(len(df), ","))

    if exclude_etf and "market_raw" in df.columns:
        market_raw_str = df["market_raw"].astype(str)
        bad = market_raw_str.str.contains(
            "ETF|REIT|出資証券|外国株|優先株|インフラファンド|ベンチャーファンド",
            regex=True, na=False,
        )
        df = df[~bad]
        safe_print("[OK] ETF/REIT 等を除外: -> " + format(len(df), ","))

    if "market_raw" in df.columns:
        df["market"] = df["market_raw"].apply(normalise_market)
    else:
        df["market"] = "Other"
    if "sector" in df.columns:
        df["sector"] = df["sector"].fillna("").astype(str)
    else:
        df["sector"] = ""
    df["theme"] = df["sector"].map(SECTOR_TO_THEME).fillna("内需・ディフェンシブ")

    out = (
        df[["code", "name", "market", "sector", "theme"]]
        .drop_duplicates(subset=["code"])
        .sort_values("code")
        .reset_index(drop=True)
    )

    if keep_themes:
        existing = Path(__file__).with_name("universe.csv")
        if existing.exists():
            try:
                old = pd.read_csv(existing, dtype={"code": str})
                old["code"] = old["code"].str.zfill(4)
                if "theme" in old.columns:
                    theme_map = dict(zip(old["code"], old["theme"]))
                    out["theme"] = out.apply(
                        lambda r: theme_map.get(r["code"], r["theme"]),
                        axis=1,
                    )
                    safe_print("[OK] 既存テーマをマージ (" + format(len(theme_map), ",") + " 件)")
            except Exception as e:
                safe_print("[!] 既存テーマのマージに失敗: " + str(e))

    return out


def main() -> int:
    safe_print("=" * 60)
    safe_print(" JPX 銘柄ユニバース更新ツール")
    safe_print("=" * 60)

    issues = preflight()
    if issues:
        safe_print("")
        safe_print("[ERROR] プリフライトチェック失敗:")
        for x in issues:
            safe_print("  * " + x)
        safe_print("")
        return 2

    p = argparse.ArgumentParser()
    p.add_argument("--include-etf", action="store_true", default=False)
    args = p.parse_args()

    try:
        out = build(keep_themes=True, exclude_etf=not args.include_etf)
    except Exception as e:
        safe_print("")
        safe_print("[ERROR] ビルド失敗:")
        safe_print("  " + type(e).__name__ + ": " + str(e))
        safe_print("")
        safe_print("--- スタックトレース ---")
        traceback.print_exc()
        safe_print("------------------------")
        return 1

    target = Path(__file__).with_name("universe.csv")
    out.to_csv(target, index=False, encoding="utf-8-sig")
    safe_print("")
    safe_print("[DONE] " + format(len(out), ",") + " 銘柄を " + target.name + " に保存しました")
    safe_print("       絶対パス: " + str(target.resolve()))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        safe_print("\n中断されました")
        sys.exit(130)
    except Exception:
        safe_print("\n予期しないエラー:")
        traceback.print_exc()
        sys.exit(1)
