"""
SIGNUM ― Index constituents & daily contribution rankings (with index-point impact).

寄与度の計算 (各銘柄が指数を何ポイント押し上げ/押し下げたか):
    - 価格加重指数 (Nikkei 225, Dow 30):
        index_points = price_change / divisor
            * Nikkei 225 divisor ≈ 28.5
            * Dow divisor ≈ 0.1517
    - 時価総額加重指数 (TOPIX Growth 250, NASDAQ 100):
        weight = (close × volume) / sum(close × volume across constituents)
        index_points = weight × pct_change × index_level
"""

from __future__ import annotations

import io
import math
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None  # type: ignore


# 価格加重指数の除数
NIKKEI_DIVISOR = 28.5
DOW_DIVISOR = 0.1517

FALLBACK_INDEX_LEVELS: dict[str, float] = {
    "nikkei225": 38000.0,
    "growth250": 700.0,
    "dow30": 40000.0,
    "nasdaq100": 20000.0,
}

INDEX_SYMBOLS: dict[str, str] = {
    "nikkei225": "^N225",
    "growth250": "2516.T",
    "dow30": "^DJI",
    "nasdaq100": "^NDX",
}

CURRENCY: dict[str, str] = {
    "nikkei225": "¥",
    "growth250": "¥",
    "dow30": "$",
    "nasdaq100": "$",
}


# ----------------------------------------------------------------------
# Constituent lists
# ----------------------------------------------------------------------
NIKKEI_225: list[tuple[str, str]] = [
    ("9983", "ファーストリテイリング"), ("8035", "東京エレクトロン"), ("6857", "アドバンテスト"),
    ("9984", "ソフトバンクG"), ("6098", "リクルートHD"), ("4063", "信越化学"),
    ("8001", "伊藤忠商事"), ("8002", "丸紅"), ("8031", "三井物産"), ("8053", "住友商事"),
    ("8058", "三菱商事"), ("9433", "KDDI"), ("9432", "NTT"), ("9434", "ソフトバンク"),
    ("7203", "トヨタ"), ("7267", "ホンダ"), ("7261", "マツダ"), ("7269", "スズキ"),
    ("7270", "SUBARU"), ("7201", "日産自"), ("6758", "ソニーG"), ("6981", "村田製作所"),
    ("6594", "ニデック"), ("6501", "日立"), ("6503", "三菱電機"), ("6701", "NEC"),
    ("6702", "富士通"), ("6752", "パナソニックHD"), ("6273", "SMC"), ("6301", "コマツ"),
    ("6326", "クボタ"), ("6367", "ダイキン工業"), ("6471", "日本精工"), ("6479", "ミネベアミツミ"),
    ("6506", "安川電機"), ("6645", "オムロン"), ("6724", "セイコーエプソン"),
    ("6753", "シャープ"), ("6762", "TDK"), ("6770", "アルプスアルパイン"),
    ("6841", "横河電機"), ("6902", "デンソー"), ("6952", "カシオ"), ("6954", "ファナック"),
    ("6971", "京セラ"), ("6976", "太陽誘電"), ("6988", "日東電工"),
    ("4502", "武田薬品"), ("4503", "アステラス製薬"), ("4506", "住友ファーマ"),
    ("4507", "塩野義製薬"), ("4519", "中外製薬"), ("4523", "エーザイ"), ("4543", "テルモ"),
    ("4568", "第一三共"), ("4578", "大塚HD"), ("4901", "富士フイルム"), ("4911", "資生堂"),
    ("4452", "花王"), ("4151", "協和キリン"), ("4188", "三菱ケミカルG"),
    ("4005", "住友化学"), ("4042", "東ソー"), ("4061", "デンカ"), ("4183", "三井化学"),
    ("4208", "宇部"), ("4272", "日本化薬"), ("4324", "電通グループ"),
    ("4661", "オリエンタルランド"), ("4689", "LINEヤフー"), ("4704", "トレンドマイクロ"),
    ("4751", "サイバーエージェント"), ("4755", "楽天G"), ("9602", "東宝"),
    ("9613", "NTTデータ"), ("9735", "セコム"), ("9766", "コナミG"),
    ("9531", "東京ガス"), ("9501", "東京電力HD"), ("9502", "中部電力"), ("9503", "関西電力"),
    ("9020", "JR東日本"), ("9021", "JR西日本"), ("9022", "JR東海"),
    ("9101", "日本郵船"), ("9104", "商船三井"), ("9107", "川崎汽船"),
    ("9202", "ANA"), ("9201", "JAL"), ("9301", "三菱倉庫"), ("9412", "スカパーJSAT"),
    ("8801", "三井不動産"), ("8802", "三菱地所"), ("8830", "住友不動産"),
    ("8267", "イオン"), ("3382", "セブン&アイ"), ("9843", "ニトリHD"), ("9989", "サンドラッグ"),
    ("2503", "キリンHD"), ("2502", "アサヒGHD"), ("2914", "JT"),
    ("2802", "味の素"), ("2801", "キッコーマン"), ("2587", "サントリーBF"),
    ("2871", "ニチレイ"), ("2002", "日清製粉G本社"), ("2768", "双日"),
    ("8306", "三菱UFJ"), ("8316", "三井住友FG"), ("8411", "みずほFG"),
    ("8604", "野村HD"), ("8473", "SBIHD"), ("8725", "MS&AD"),
    ("8750", "第一生命HD"), ("8766", "東京海上HD"), ("8795", "T&DHD"),
    ("1605", "INPEX"), ("1721", "コムシスHD"), ("1801", "大成建設"),
    ("1802", "大林組"), ("1803", "清水建設"), ("1808", "長谷工コーポレーション"),
    ("1812", "鹿島"), ("1925", "大和ハウス工業"), ("1928", "積水ハウス"),
    ("1963", "日揮HD"), ("3401", "帝人"), ("3402", "東レ"), ("3407", "旭化成"),
    ("3863", "日本製紙"), ("3865", "北越コーポレーション"), ("5108", "ブリヂストン"),
    ("5202", "日板硝"), ("5232", "住友大阪セメント"), ("5301", "東海カーボン"),
    ("5332", "TOTO"), ("5333", "ガイシ"), ("5401", "日本製鉄"),
    ("5406", "神戸製鋼"), ("5411", "JFEHD"), ("5631", "日本製鋼所"),
    ("5703", "日本軽金属HD"), ("5706", "三井金属"), ("5713", "住友金属鉱山"),
    ("5714", "DOWA"), ("5801", "古河電気工業"), ("5802", "住友電気工業"),
    ("5803", "フジクラ"), ("5901", "東洋製罐G HD"),
    ("7011", "三菱重工業"), ("7012", "川崎重工業"), ("7013", "IHI"),
    ("7211", "三菱自動車"), ("7762", "シチズン時計"),
    ("7733", "オリンパス"), ("7741", "HOYA"), ("7751", "キヤノン"),
    ("7752", "リコー"), ("7832", "バンダイナムコHD"), ("7912", "大日本印刷"),
    ("7951", "ヤマハ"), ("8015", "豊田通商"), ("8233", "高島屋"),
]

GROWTH_250: list[tuple[str, str]] = [
    ("3923", "ラクス"), ("4385", "メルカリ"), ("4477", "BASE"), ("4478", "フリー"),
    ("4480", "メドレー"), ("4194", "ビジョナル"), ("4490", "ビザスク"),
    ("4498", "サイバートラスト"), ("4499", "Speee"), ("4011", "ヘッドウォータース"),
    ("4053", "Sun Asterisk"), ("4056", "ニューラル"), ("4165", "プレイド"),
    ("4166", "かっこ"), ("4168", "ヤプリ"), ("4169", "ENECHANGE"),
    ("4170", "Kaizen Platform"), ("4180", "Appier Group"), ("4374", "ROBOT PAYMENT"),
    ("4382", "HEROZ"), ("4384", "ラクスル"), ("4413", "ボードルア"),
    ("4417", "グローバルセキュリティエキスパート"), ("4418", "JDSC"),
    ("4424", "Amazia"), ("4425", "Kudan"), ("4432", "ウィザス"),
    ("4441", "トビラシステムズ"), ("4443", "Sansan"), ("4448", "Chatwork"),
    ("4449", "ギフティ"), ("4475", "HENNGE"), ("4476", "AI inside"),
    ("4485", "JTOWER"), ("4488", "AI CROSS"), ("4493", "サイバーセキュリティクラウド"),
    ("4495", "アイキューブドシステムズ"), ("4934", "プレミアアンチエイジング"),
    ("4575", "キャンバス"), ("4593", "ヘリオス"), ("4571", "ナノキャリア"),
    ("4978", "リプロセル"), ("3993", "PKSHA Technology"), ("3994", "マネーフォワード"),
    ("3998", "すららネット"), ("3917", "アイリッジ"), ("3922", "PR TIMES"),
    ("3935", "エディア"), ("3962", "チェンジHD"), ("3978", "マクロミル"),
    ("3984", "ユーザーローカル"), ("3987", "エコモット"), ("3989", "シェアリングテクノロジー"),
    ("3990", "UUUM"), ("3991", "ウォンテッドリー"), ("4034", "Liberaware"),
    ("4068", "ベイシス"), ("4252", "ケイファーマ"), ("4255", "THECOO"),
    ("4259", "エクサウィザーズ"), ("4260", "ハイブリッドテクノロジーズ"),
    ("4263", "サスメド"), ("4264", "セキュア"), ("4265", "いい生活"),
    ("5132", "pluszero"), ("5253", "カバー"), ("5025", "マーキュリーリアルテックイノベ"),
    ("5026", "トリプルアイズ"), ("5036", "JBS"), ("5038", "eWeLL"),
    ("5039", "アイモバイル"), ("5246", "ELEMENTS"),
    ("6034", "MRT"), ("6035", "IRJapan"), ("6038", "イード"),
    ("6044", "三機サービス"), ("6046", "リンクバル"), ("6058", "ベクトル"),
    ("6090", "ヒューマン・メタボローム・テクノロジーズ"), ("6094", "フリークアウト"),
    ("6172", "メタリアル"), ("6175", "ネットマーケティング"),
    ("6193", "バーチャレクス・コンサルティング"), ("6200", "インソース"),
    ("6232", "ACSL"), ("6533", "オーケストラHD"), ("6541", "グレイステクノロジー"),
    ("6552", "GameWith"), ("6553", "ソウルドアウト"), ("6557", "AIAIグループ"),
    ("6562", "ジーニー"), ("6577", "ベストワンドットコム"), ("7036", "イーエムシステムズ"),
    ("7050", "FFRIセキュリティ"), ("7068", "フィードフォース"), ("7069", "サイバーバズ"),
    ("7072", "インティメート・マージャー"), ("7078", "INCLUSIVE"),
    ("7089", "フォースタートアップス"), ("7095", "Macbee Planet"),
    ("7378", "アシロ"), ("7379", "サーキュレーション"), ("7383", "ネットプロテクションズHD"),
    ("7388", "FPパートナー"), ("9229", "Lib Work"), ("9466", "アイドマMC"),
    ("9468", "KADOKAWA"), ("9252", "ラストワンマイル"), ("9341", "GENOVA"),
    ("9342", "スマサポ"), ("9344", "アクシスコンサルティング"),
    ("9346", "ハイブリッドテクノロジーズ"), ("9351", "ハーモニックジャパン"),
    ("9519", "レノバ"),
]

DOW_30: list[tuple[str, str]] = [
    ("AAPL", "Apple"), ("AMGN", "Amgen"), ("AMZN", "Amazon"), ("AXP", "American Express"),
    ("BA", "Boeing"), ("CAT", "Caterpillar"), ("CRM", "Salesforce"), ("CSCO", "Cisco"),
    ("CVX", "Chevron"), ("DIS", "Disney"), ("GS", "Goldman Sachs"), ("HD", "Home Depot"),
    ("HON", "Honeywell"), ("IBM", "IBM"), ("JNJ", "Johnson & Johnson"),
    ("JPM", "JPMorgan Chase"), ("KO", "Coca-Cola"), ("MCD", "McDonald's"),
    ("MMM", "3M"), ("MRK", "Merck"), ("MSFT", "Microsoft"), ("NKE", "Nike"),
    ("NVDA", "NVIDIA"), ("PG", "Procter & Gamble"), ("SHW", "Sherwin-Williams"),
    ("TRV", "Travelers"), ("UNH", "UnitedHealth"), ("V", "Visa"),
    ("VZ", "Verizon"), ("WMT", "Walmart"),
]

NASDAQ_100: list[tuple[str, str]] = [
    ("AAPL", "Apple"), ("MSFT", "Microsoft"), ("NVDA", "NVIDIA"), ("AMZN", "Amazon"),
    ("META", "Meta Platforms"), ("GOOGL", "Alphabet A"), ("GOOG", "Alphabet C"),
    ("TSLA", "Tesla"), ("AVGO", "Broadcom"), ("COST", "Costco"),
    ("ADBE", "Adobe"), ("NFLX", "Netflix"), ("AMD", "AMD"), ("PEP", "PepsiCo"),
    ("CSCO", "Cisco"), ("TMUS", "T-Mobile"), ("INTC", "Intel"), ("CMCSA", "Comcast"),
    ("INTU", "Intuit"), ("QCOM", "Qualcomm"), ("AMGN", "Amgen"), ("HON", "Honeywell"),
    ("AMAT", "Applied Materials"), ("BKNG", "Booking Holdings"), ("ISRG", "Intuitive Surgical"),
    ("VRTX", "Vertex Pharma"), ("ADP", "ADP"), ("PANW", "Palo Alto Networks"),
    ("SBUX", "Starbucks"), ("MU", "Micron"), ("GILD", "Gilead"),
    ("ADI", "Analog Devices"), ("LRCX", "Lam Research"), ("REGN", "Regeneron"),
    ("MDLZ", "Mondelez"), ("KLAC", "KLA Corp"), ("SNPS", "Synopsys"),
    ("CDNS", "Cadence Design"), ("PYPL", "PayPal"), ("MAR", "Marriott"),
    ("CRWD", "CrowdStrike"), ("MELI", "MercadoLibre"), ("ABNB", "Airbnb"),
    ("FTNT", "Fortinet"), ("ORLY", "O'Reilly Auto"), ("CSX", "CSX"),
    ("WDAY", "Workday"), ("CHTR", "Charter Comm"), ("ADSK", "Autodesk"),
    ("ROP", "Roper Tech"), ("NXPI", "NXP Semiconductors"), ("FANG", "Diamondback"),
    ("PCAR", "PACCAR"), ("MNST", "Monster Beverage"), ("KDP", "Keurig Dr Pepper"),
    ("PAYX", "Paychex"), ("ODFL", "Old Dominion Freight"), ("AEP", "American Electric"),
    ("EXC", "Exelon"), ("CPRT", "Copart"), ("MRVL", "Marvell Tech"),
    ("CTAS", "Cintas"), ("DXCM", "Dexcom"), ("ROST", "Ross Stores"),
    ("KHC", "Kraft Heinz"), ("AZN", "AstraZeneca"), ("LULU", "Lululemon"),
    ("FAST", "Fastenal"), ("BIIB", "Biogen"), ("EA", "Electronic Arts"),
    ("VRSK", "Verisk"), ("XEL", "Xcel Energy"), ("CTSH", "Cognizant"),
    ("IDXX", "IDEXX Labs"), ("DLTR", "Dollar Tree"), ("ON", "ON Semiconductor"),
    ("WBD", "Warner Bros Discovery"), ("TEAM", "Atlassian"),
    ("DDOG", "Datadog"), ("ZS", "Zscaler"), ("MDB", "MongoDB"),
    ("SIRI", "SiriusXM"), ("ANSS", "Ansys"), ("ILMN", "Illumina"),
    ("CCEP", "Coca-Cola Europacific"), ("GFS", "GlobalFoundries"),
    ("WBA", "Walgreens Boots"), ("PDD", "PDD Holdings"),
    ("MCHP", "Microchip Tech"), ("BKR", "Baker Hughes"), ("CDW", "CDW Corp"),
    ("GEHC", "GE HealthCare"), ("TTD", "Trade Desk"), ("ZM", "Zoom"),
    ("DOCU", "DocuSign"), ("OKTA", "Okta"),
    ("PLTR", "Palantir"), ("SNOW", "Snowflake"),
]


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _batch_download(symbols: list[str], period: str = "5d") -> pd.DataFrame:
    if yf is None or not symbols:
        return pd.DataFrame()
    try:
        df = yf.download(
            " ".join(symbols), period=period, interval="1d",
            auto_adjust=True, progress=False, threads=True, group_by="ticker",
        )
    except Exception:
        return pd.DataFrame()
    return df if df is not None and not df.empty else pd.DataFrame()


def _extract_sub(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        if symbol not in df.columns.get_level_values(0):
            return pd.DataFrame()
        try:
            sub = df[symbol]
            return sub.dropna(subset=["Close"]) if "Close" in sub.columns else pd.DataFrame()
        except Exception:
            return pd.DataFrame()
    else:
        return df.dropna(subset=["Close"]) if "Close" in df.columns else pd.DataFrame()


def _fetch_index_snapshot(symbol: str) -> dict:
    """指数本体の最新値・前日比・前日比%を取得。失敗時は空 dict。"""
    if yf is None or not symbol:
        return {}
    try:
        df = yf.download(symbol, period="5d", interval="1d",
                         auto_adjust=True, progress=False, threads=False)
        if df is None or df.empty:
            return {}
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close = df["Close"].dropna()
        if len(close) < 2:
            return {}
        latest = float(close.iloc[-1])
        prev = float(close.iloc[-2])
        change = latest - prev
        pct = (latest / prev - 1) if prev > 0 else 0.0
        as_of = close.index[-1]
        return {
            "level": latest,
            "prev_close": prev,
            "change": change,
            "pct_change": pct,
            "as_of": as_of.strftime("%Y-%m-%d") if hasattr(as_of, "strftime") else "",
        }
    except Exception:
        return {}


def _fetch_index_level(symbol: str) -> float | None:
    snap = _fetch_index_snapshot(symbol)
    return snap.get("level") if snap else None


# ----------------------------------------------------------------------
# Compute contributors with index-point impact
# ----------------------------------------------------------------------
def compute_contributors(
    constituents: list[tuple[str, str]],
    suffix: str = "",
    weight: str = "price",
    divisor: float | None = None,
    index_level: float | None = None,
    top_n: int = 10,
) -> dict:
    """指数構成銘柄の当日寄与度ランキングを、指数ポイント単位で計算。"""
    symbols = [t + suffix for t, _ in constituents]
    df = _batch_download(symbols, period="7d")
    if df.empty:
        return {"as_of": "", "up": [], "down": [], "total_processed": 0,
                "errors": 0, "total_index_points_up": 0.0,
                "total_index_points_down": 0.0,
                "index_level": index_level, "divisor": divisor,
                "weight_type": weight}

    rows: list[dict] = []
    errors = 0
    latest_date = None

    for ticker, name in constituents:
        sym = ticker + suffix
        sub = _extract_sub(df, sym)
        if sub.empty or len(sub) < 2:
            errors += 1
            continue
        try:
            sub = sub.sort_index()
            today = sub.iloc[-1]
            prev = sub.iloc[-2]
            today_close = float(today["Close"])
            prev_close = float(prev["Close"])
            vol_today = float(today.get("Volume", 0) or 0)
            if today_close <= 0 or prev_close <= 0:
                errors += 1
                continue
            price_change = today_close - prev_close
            pct_change = (today_close / prev_close) - 1
            rows.append({
                "ticker": ticker, "name": name,
                "close": today_close, "prev_close": prev_close,
                "price_change": price_change, "pct_change": pct_change,
                "volume": vol_today,
                "cap_proxy": today_close * vol_today,
            })
            if latest_date is None or sub.index[-1] > latest_date:
                latest_date = sub.index[-1]
        except Exception:
            errors += 1
            continue

    if weight == "price":
        d = divisor if (divisor and divisor > 0) else 1.0
        for r in rows:
            r["index_points"] = r["price_change"] / d
    else:
        total_cap = sum(r["cap_proxy"] for r in rows if r["cap_proxy"] > 0)
        lvl = index_level if (index_level and index_level > 0) else 1.0
        for r in rows:
            if total_cap > 0 and r["cap_proxy"] > 0:
                w = r["cap_proxy"] / total_cap
                r["index_points"] = w * r["pct_change"] * lvl
            else:
                r["index_points"] = 0.0

    rows.sort(key=lambda x: x["index_points"], reverse=True)
    up = [r for r in rows if r["index_points"] > 0][:top_n]
    down_all = [r for r in rows if r["index_points"] < 0]
    down_all.sort(key=lambda x: x["index_points"])
    down = down_all[:top_n]

    total_up = sum(r["index_points"] for r in up)
    total_down = sum(r["index_points"] for r in down)

    return {
        "as_of": latest_date.strftime("%Y-%m-%d") if latest_date is not None else "",
        "up": up,
        "down": down,
        "total_processed": len(rows),
        "errors": errors,
        "total_index_points_up": total_up,
        "total_index_points_down": total_down,
        "index_level": index_level,
        "divisor": divisor,
        "weight_type": weight,
    }


def _wrap_with_snapshot(name_key: str, res: dict) -> dict:
    """compute_contributors の結果に index_snapshot (本体値・変動・変動率) を埋め込む。"""
    snap = _fetch_index_snapshot(INDEX_SYMBOLS.get(name_key, ""))
    res["index_snapshot"] = snap
    # 取得できれば index_level も上書きしてより正確に
    if snap and snap.get("level"):
        res["index_level"] = snap["level"]
    return res


def get_nikkei_225_contributors(top_n: int = 10) -> dict:
    res = compute_contributors(
        NIKKEI_225, suffix=".T", weight="price",
        divisor=NIKKEI_DIVISOR, top_n=top_n,
    )
    return _wrap_with_snapshot("nikkei225", res)


def get_growth_250_contributors(top_n: int = 10) -> dict:
    snap = _fetch_index_snapshot(INDEX_SYMBOLS["growth250"])
    level = (snap.get("level") if snap else None) or FALLBACK_INDEX_LEVELS["growth250"]
    res = compute_contributors(
        GROWTH_250, suffix=".T", weight="mcap",
        index_level=level, top_n=top_n,
    )
    res["index_snapshot"] = snap
    if snap and snap.get("level"):
        res["index_level"] = snap["level"]
    return res


def get_dow_30_contributors(top_n: int = 10) -> dict:
    res = compute_contributors(
        DOW_30, suffix="", weight="price",
        divisor=DOW_DIVISOR, top_n=top_n,
    )
    return _wrap_with_snapshot("dow30", res)


def get_nasdaq_100_contributors(top_n: int = 10) -> dict:
    snap = _fetch_index_snapshot(INDEX_SYMBOLS["nasdaq100"])
    level = (snap.get("level") if snap else None) or FALLBACK_INDEX_LEVELS["nasdaq100"]
    res = compute_contributors(
        NASDAQ_100, suffix="", weight="mcap",
        index_level=level, top_n=top_n,
    )
    res["index_snapshot"] = snap
    if snap and snap.get("level"):
        res["index_level"] = snap["level"]
    return res
