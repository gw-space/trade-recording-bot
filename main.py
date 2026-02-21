#!/usr/bin/env python3
import json
import os
import re
import time
import traceback
import hashlib
import uuid
import warnings
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote, urlencode
from zoneinfo import ZoneInfo

# Hide non-critical runtime warnings in this long-running bot process.
warnings.filterwarnings(
    "ignore",
    message=r"You are using a Python version 3\.9 past its end of life.*",
    category=FutureWarning,
)
warnings.filterwarnings(
    "ignore",
    message=r"urllib3 v2 only supports OpenSSL 1\.1\.1\+.*",
    category=Warning,
)
warnings.filterwarnings(
    "ignore",
    message=r"The HMAC key is .* below the minimum recommended length.*",
    category=Warning,
)

import gspread
import jwt
import requests
from dotenv import load_dotenv
from google.auth.transport.requests import AuthorizedSession, Request


@dataclass
class FillMessage:
    raw_text: str
    symbol: str
    trade_side: str
    fill_price: float
    fill_qty: float
    fill_month: int
    fill_day: int


@dataclass
class FillResult:
    spreadsheet_title: str
    currency: str
    avg_price_r6: float
    current_price_b2: float
    buy_loc_avg_r9: float
    buy_loc_high_r10: float
    sell_all_r11: float
    sell_qty_current_round: float


@dataclass
class UpbitFill:
    fill_id: str
    market: str
    trade_time: datetime
    side: str
    price: float
    qty: float
    amount: float


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def backup_spreadsheet_to_local(sh: gspread.Spreadsheet, backup_dir: str, context: str, bucket: str) -> Path:
    safe_bucket = re.sub(r"[^0-9A-Za-z._-]+", "_", bucket).strip("_") or "misc"
    target_dir = Path(backup_dir) / safe_bucket
    target_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_title = re.sub(r"[^0-9A-Za-z._-]+", "_", sh.title).strip("_") or "spreadsheet"
    safe_context = re.sub(r"[^0-9A-Za-z._-]+", "_", context).strip("_") or "run"
    out_path = target_dir / f"{ts}_{safe_title}_{sh.id}_{safe_context}.xlsx"

    creds = sh.client.auth
    if not creds.valid:
        creds.refresh(Request())
    authed = AuthorizedSession(creds)
    export_url = f"https://www.googleapis.com/drive/v3/files/{sh.id}/export"
    resp = authed.get(
        export_url,
        params={"mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        timeout=60,
    )
    resp.raise_for_status()
    out_path.write_bytes(resp.content)
    return out_path


def ensure_spreadsheet_backup_once(
    sh: gspread.Spreadsheet,
    backup_dir: str,
    backup_cache: set,
    backup_context: str,
    backup_bucket: str,
) -> None:
    key = f"{sh.id}:{backup_context}:{backup_bucket}"
    if key in backup_cache:
        return
    p = backup_spreadsheet_to_local(sh, backup_dir, backup_context, backup_bucket)
    backup_cache.add(key)
    log(f"spreadsheet_backup_done path={p}")


def parse_kv_message(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k.strip()] = v.strip()
    return out


def parse_float(text: str) -> float:
    m = re.search(r"[-+]?\d+(?:\.\d+)?", text.replace(",", ""))
    if not m:
        raise ValueError(f"number not found: {text}")
    return float(m.group(0))


def get_numeric_cell_value(ws: gspread.Worksheet, a1: str) -> float:
    # Prefer computed numeric value, not formula text.
    raw = ws.acell(a1, value_render_option="UNFORMATTED_VALUE").value
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        s = raw.strip()
        if s.startswith("="):
            raise ValueError(f"{a1} 값이 수식 문자열로 반환되었습니다: {s}")
        return parse_float(s)
    raise ValueError(f"{a1} 숫자 값을 읽을 수 없습니다: {raw!r}")


def get_numeric_cell_value_or_none(ws: gspread.Worksheet, a1: str) -> Optional[float]:
    try:
        return get_numeric_cell_value(ws, a1)
    except Exception:
        return None


def format_two_decimals(v: float) -> str:
    return f"{v:.2f}"


def detect_currency_by_sheet_title(title: str) -> str:
    t = (title or "").upper()
    if "TQQQ" in t:
        return "USD"
    if "BTC" in t or "비트코인" in title:
        return "KRW"
    return "USD"


def currency_from_symbol(symbol: str) -> str:
    s = (symbol or "").upper()
    if s == "BTC":
        return "KRW"
    if s == "TQQQ":
        return "USD"
    return "USD"


def format_money(v: float, ccy: str) -> str:
    if ccy == "KRW":
        return f"₩{v:,.2f}"
    return f"${v:,.2f}"


def parse_symbol(stock_name: str) -> str:
    m = re.search(r"\(([^)]+)\)", stock_name)
    if not m:
        raise ValueError(f"symbol not found in 종목명: {stock_name}")
    return m.group(1).strip().upper()


def parse_fill_date(mmdd: str, tz_name: str) -> Tuple[int, int, int]:
    m = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})", mmdd)
    if not m:
        raise ValueError(f"invalid 체결일자: {mmdd}")
    month = int(m.group(1))
    day = int(m.group(2))
    year = datetime.now(ZoneInfo(tz_name)).year
    return year, month, day


def parse_fill_message(text: str, tz_name: str) -> Optional[FillMessage]:
    if "[메리츠증권] 해외주식 주문체결 안내" not in text:
        return None

    kv = parse_kv_message(text)
    stock_name = kv.get("종목명", "")
    trade_side = kv.get("매매구분", "")
    fill_price_raw = kv.get("체결단가", "")
    fill_qty_raw = kv.get("체결수량", "")
    fill_date_raw = kv.get("체결일자", "")

    if not all([stock_name, trade_side, fill_price_raw, fill_qty_raw, fill_date_raw]):
        return None

    symbol = parse_symbol(stock_name)
    fill_price = parse_float(fill_price_raw)
    fill_qty = parse_float(fill_qty_raw)
    _, month, day = parse_fill_date(fill_date_raw, tz_name)

    return FillMessage(
        raw_text=text,
        symbol=symbol,
        trade_side=trade_side,
        fill_price=fill_price,
        fill_qty=fill_qty,
        fill_month=month,
        fill_day=day,
    )


def parse_spreadsheet_id_map(raw: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for item in raw.split(","):
        pair = item.strip()
        if not pair or ":" not in pair:
            continue
        symbol, sheet_id = pair.split(":", 1)
        symbol = symbol.strip().upper()
        sheet_id = sheet_id.strip()
        if symbol and sheet_id:
            out[symbol] = sheet_id
    return out


def get_fill_result_for_row(
    ws: gspread.Worksheet, sh_title: str, target_row: int, total_qty_col: int, symbol_hint: str = ""
) -> FillResult:
    sell_qty = get_numeric_cell_value_or_none(ws, f"{col_to_a1(total_qty_col)}{target_row}")
    ccy = currency_from_symbol(symbol_hint) if symbol_hint else detect_currency_by_sheet_title(sh_title)
    return FillResult(
        spreadsheet_title=sh_title,
        currency=ccy,
        avg_price_r6=get_numeric_cell_value(ws, "R6"),
        current_price_b2=get_numeric_cell_value(ws, "B2"),
        buy_loc_avg_r9=get_numeric_cell_value(ws, "R9"),
        buy_loc_high_r10=get_numeric_cell_value(ws, "R10"),
        sell_all_r11=get_numeric_cell_value(ws, "R11"),
        sell_qty_current_round=sell_qty if sell_qty is not None else 0.0,
    )


def build_reply_text(result: FillResult) -> str:
    ccy = result.currency if result.currency else detect_currency_by_sheet_title(result.spreadsheet_title)
    return (
        f"구글스프레드시트({result.spreadsheet_title}) 기입 완료\n"
        f"현재 평단가 : {format_money(result.avg_price_r6, ccy)}\n"
        f"현재 주가 : {format_money(result.current_price_b2, ccy)}\n\n"
        f"오늘 매수 시도액\n"
        f"LOC 평단 : {format_money(result.buy_loc_avg_r9, ccy)}\n"
        f"LOC 큰수 : {format_money(result.buy_loc_high_r10, ccy)}\n\n"
        f"오늘 매도 시도액\n"
        f"매도 지정가 : {format_money(result.sell_all_r11, ccy)}\n"
        f"매도 수량 : {result.sell_qty_current_round}"
    )


def build_upbit_command_result_text(processed_count: int, written_count: int, result: Optional[FillResult]) -> str:
    if written_count == 0 or result is None:
        return (
            "업비트 기록 수행 완료\n"
            f"- 처리 체결 수: {processed_count}\n"
            f"- 시트 기입 수: {written_count}"
        )
    return (
        "업비트 기록 수행 완료\n"
        f"- 처리 체결 수: {processed_count}\n"
        f"- 시트 기입 수: {written_count}\n\n"
        f"{build_reply_text(result)}"
    )


def parse_upbit_command_date(text: str, command_text: str, tz_name: str) -> Optional[Tuple[date, bool]]:
    pattern = rf"^\s*{re.escape(command_text)}(?:\s*:\s*(\d{{2,4}}-\d{{2}}-\d{{2}}))?\s*$"
    m = re.match(pattern, text.strip())
    if not m:
        return None
    d = m.group(1)
    if not d:
        return datetime.now(ZoneInfo(tz_name)).date(), False
    if len(d.split("-", 1)[0]) == 2:
        yy, mm, dd = d.split("-")
        d = f"20{yy}-{mm}-{dd}"
    return datetime.strptime(d, "%Y-%m-%d").date(), True


def upbit_auth_headers(access_key: str, secret_key: str, params: Dict[str, str]) -> Dict[str, str]:
    # Upbit query_hash must match the exact query-string encoding.
    query = unquote(urlencode(params, doseq=True))
    payload = {
        "access_key": access_key,
        "nonce": str(uuid.uuid4()),
        "query_hash": hashlib.sha512(query.encode("utf-8")).hexdigest(),
        "query_hash_alg": "SHA512",
    }
    token = jwt.encode(payload, secret_key, algorithm="HS512")
    return {"Authorization": f"Bearer {token}"}


def fetch_upbit_fills_for_date(
    tz_name: str,
    target_date: date,
    access_key: str,
    secret_key: str,
    market_filter: str,
    market_asset_filter: str,
    base_url: str = "https://api.upbit.com",
    orders_path: str = "/v1/orders/closed",
) -> List[UpbitFill]:
    page = 1
    out: List[UpbitFill] = []
    max_pages = int(os.getenv("UPBIT_MAX_PAGES", "30"))
    total_rows = 0
    skip_market = 0
    skip_qty = 0
    skip_amount = 0
    skip_date = 0
    skip_side = 0
    while True:
        if page > max_pages:
            break
        # Include both fully-filled(done) and canceled-with-executions(cancel) orders.
        params = {"states[]": ["done", "cancel"], "page": str(page), "limit": "100", "order_by": "desc"}
        headers = upbit_auth_headers(access_key, secret_key, params)
        resp = requests.get(f"{base_url}{orders_path}", params=params, headers=headers, timeout=20)
        if resp.status_code in {404, 405} and orders_path != "/v1/orders":
            # Backward compatibility fallback.
            resp = requests.get(f"{base_url}/v1/orders", params=params, headers=headers, timeout=20)
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            break
        total_rows += len(rows)
        for row in rows:
            done_ts = row.get("done_at")
            created_ts = row.get("created_at")
            if not done_ts and not created_ts:
                continue

            done_dt = (
                datetime.fromisoformat(str(done_ts).replace("Z", "+00:00")).astimezone(ZoneInfo(tz_name))
                if done_ts
                else None
            )
            created_dt = (
                datetime.fromisoformat(str(created_ts).replace("Z", "+00:00")).astimezone(ZoneInfo(tz_name))
                if created_ts
                else None
            )

            done_date = done_dt.date() if done_dt else None
            created_date = created_dt.date() if created_dt else None
            if target_date not in {done_date, created_date}:
                skip_date += 1
                continue
            market = str(row.get("market", ""))
            base_asset = market.split("-")[-1].upper() if "-" in market else market.upper()
            # Enforce BTC-only handling regardless of external config.
            if base_asset != "BTC":
                skip_market += 1
                continue
            if market_filter and market != market_filter:
                if market_asset_filter:
                    if base_asset != market_asset_filter.upper():
                        skip_market += 1
                        continue
                else:
                    skip_market += 1
                    continue
            side = str(row.get("side", ""))
            # Enforce buy-only handling.
            if side != "bid":
                skip_side += 1
                continue
            ord_type = str(row.get("ord_type", ""))
            qty = float(row.get("executed_volume") or 0)
            executed_funds = float(row.get("executed_funds") or 0)
            raw_price = float(row.get("price") or 0)
            # For market orders, "price" can be empty; derive from funds/volume.
            if qty <= 0:
                skip_qty += 1
                continue
            # Upbit market buy(ord_type=price): `price` is total spend amount (KRW), not unit price.
            if side == "bid" and ord_type == "price" and raw_price > 0:
                amount = raw_price
            else:
                amount = executed_funds if executed_funds > 0 else (raw_price * qty if raw_price > 0 else 0.0)
            if amount <= 0:
                skip_amount += 1
                continue
            if side == "bid" and ord_type == "price":
                price = amount / qty
            else:
                price = raw_price if raw_price > 0 else (amount / qty)
            trade_dt = done_dt or created_dt
            fill_id = str(row.get("uuid") or f"{market}:{trade_dt.isoformat()}:{qty}:{price}")
            out.append(
                UpbitFill(
                    fill_id=fill_id,
                    market=market,
                    trade_time=trade_dt,
                    side=side,
                    price=price,
                    qty=qty,
                    amount=amount,
                )
            )
        page += 1
    log(
        f"upbit_fetch_done target_date={target_date.isoformat()} market={market_filter} asset={market_asset_filter} "
        f"rows={total_rows} fills={len(out)} skip_date={skip_date} "
        f"skip_market={skip_market} skip_side={skip_side} skip_qty={skip_qty} skip_amount={skip_amount} pages={page-1}"
    )
    return out


def resolve_spreadsheet(gc: gspread.Client, symbol: str):
    raw_map = os.getenv("SPREADSHEET_ID_MAP", "").strip()
    id_map = parse_spreadsheet_id_map(raw_map)
    sheet_id = id_map.get(symbol)
    if sheet_id:
        return gc.open_by_key(sheet_id)

    fallback_by_title = os.getenv("FALLBACK_OPEN_BY_TITLE", "false").lower().strip() in {"1", "true", "yes", "on"}
    if fallback_by_title:
        return gc.open(f"{symbol} 무한매수")

    raise ValueError(
        f"SPREADSHEET_ID_MAP에 {symbol} 키가 없습니다. 예: SPREADSHEET_ID_MAP=TQQQ:<spreadsheet_id>"
    )


def col_to_a1(col_idx: int) -> str:
    chars: List[str] = []
    n = col_idx
    while n > 0:
        n, rem = divmod(n - 1, 26)
        chars.append(chr(ord("A") + rem))
    return "".join(reversed(chars))


def normalize_date_value(value: str) -> Optional[datetime.date]:
    value = str(value).strip()
    if not value:
        return None

    for fmt in ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y.%m.%d"]:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", value)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()

    return None


def _norm_label(text: str) -> str:
    s = str(text or "").strip().lower()
    s = re.sub(r"\s+", "", s)
    return s


def _is_date_label(text: str) -> bool:
    n = _norm_label(text)
    return "날짜" in n or "체결일자" in n


def _is_loc_avg_label(text: str) -> bool:
    n = _norm_label(text)
    return "loc평단" in n or ("loc" in n and "평단" in n)


def _is_loc_high_label(text: str) -> bool:
    n = _norm_label(text)
    return "loc고가" in n or ("loc" in n and "고가" in n)


def _is_total_qty_label(text: str) -> bool:
    n = _norm_label(text)
    return "총수량" in n


def find_header_row_and_columns(values: List[List[str]]) -> Tuple[int, int, int, int]:
    # returns: header_row(1-based), date_col, loc_avg_col, loc_high_col
    if not values:
        raise ValueError("시트가 비어 있습니다")

    max_col = max(len(r) for r in values)
    row_count = len(values)

    # 1) 날짜 라벨을 기준으로 주변에서 LOC 라벨을 찾는다.
    for r in range(1, row_count + 1):
        row = values[r - 1]
        for c in range(1, len(row) + 1):
            if not _is_date_label(row[c - 1]):
                continue

            loc_avg = None
            loc_high = None
            loc_avg_row = r
            loc_high_row = r

            for rr in range(r, min(r + 2, row_count) + 1):
                scan_row = values[rr - 1]
                for cc in range(c + 1, min(c + 14, max_col) + 1):
                    cell = scan_row[cc - 1] if cc - 1 < len(scan_row) else ""
                    if (loc_avg is None) and _is_loc_avg_label(cell):
                        loc_avg = cc
                        loc_avg_row = rr
                    if (loc_high is None) and _is_loc_high_label(cell):
                        loc_high = cc
                        loc_high_row = rr
                if loc_avg is not None and loc_high is not None:
                    header_row = max(r, loc_avg_row, loc_high_row)
                    return header_row, c, loc_avg, loc_high

    # 2) fallback: 전체에서 LOC 라벨을 찾고, 같은/인접 헤더행의 날짜를 찾는다.
    loc_avg_col = None
    loc_high_col = None
    loc_avg_row = None
    loc_high_row = None
    for r in range(1, row_count + 1):
        row = values[r - 1]
        for c in range(1, len(row) + 1):
            cell = row[c - 1]
            if loc_avg_col is None and _is_loc_avg_label(cell):
                loc_avg_col, loc_avg_row = c, r
            if loc_high_col is None and _is_loc_high_label(cell):
                loc_high_col, loc_high_row = c, r
        if loc_avg_col is not None and loc_high_col is not None:
            break

    if loc_avg_col is not None and loc_high_col is not None:
        candidate_rows = [x for x in [loc_avg_row, loc_high_row] if x is not None]
        for base_r in candidate_rows:
            for rr in [base_r, base_r - 1, base_r + 1]:
                if rr < 1 or rr > row_count:
                    continue
                scan_row = values[rr - 1]
                for c in range(1, len(scan_row) + 1):
                    if _is_date_label(scan_row[c - 1]):
                        header_row = max(rr, loc_avg_row or rr, loc_high_row or rr)
                        return header_row, c, loc_avg_col, loc_high_col

    raise ValueError("헤더 행(날짜/LOC평단/LOC고가)을 찾을 수 없습니다")


def find_total_qty_column(values: List[List[str]], header_row: int, loc_high_col: int) -> int:
    row_count = len(values)
    for rr in [header_row, header_row - 1, header_row + 1]:
        if rr < 1 or rr > row_count:
            continue
        row = values[rr - 1]
        for c in range(1, len(row) + 1):
            if _is_total_qty_label(row[c - 1]):
                return c
    # layout fallback (D/E/F/G/H/I/J pattern)
    return loc_high_col + 4


def find_or_create_date_row(
    ws: gspread.Worksheet,
    values: List[List[str]],
    header_row: int,
    date_col: int,
    target_date,
    target_date_text: str,
) -> int:
    # find existing date row
    for r_idx in range(header_row + 1, len(values) + 1):
        row = values[r_idx - 1]
        raw = row[date_col - 1] if len(row) >= date_col else ""
        parsed = normalize_date_value(raw)
        if parsed and parsed == target_date:
            return r_idx

    # create in first empty date cell below header
    r_idx = header_row + 1
    while True:
        raw = ws.acell(f"{col_to_a1(date_col)}{r_idx}").value
        if not str(raw or "").strip():
            ws.update(range_name=f"{col_to_a1(date_col)}{r_idx}", values=[[target_date_text]])
            return r_idx
        r_idx += 1


def process_fill_to_sheet(
    gc: gspread.Client,
    msg: FillMessage,
    tz_name: str,
    worksheet_name: str,
    backup_dir: str,
    backup_cache: set,
    backup_context: str,
) -> Optional[FillResult]:
    if msg.trade_side != "매수":
        return None
    if msg.fill_qty < 0:
        return None

    sh = resolve_spreadsheet(gc, msg.symbol)
    ensure_spreadsheet_backup_once(sh, backup_dir, backup_cache, backup_context, msg.symbol)
    ws = sh.worksheet(worksheet_name) if worksheet_name else sh.get_worksheet(0)

    values = ws.get_all_values()
    header_row, date_col, loc_avg_col, loc_high_col = find_header_row_and_columns(values)
    total_qty_col = find_total_qty_column(values, header_row, loc_high_col)

    year = datetime.now(ZoneInfo(tz_name)).year
    target_date = datetime(year, msg.fill_month, msg.fill_day).date()
    target_date_text = f"{year}-{msg.fill_month:02d}-{msg.fill_day:02d}"

    target_row = find_or_create_date_row(ws, values, header_row, date_col, target_date, target_date_text)

    avg_price = get_numeric_cell_value(ws, "R6")

    if msg.fill_price <= avg_price:
        price_col = loc_avg_col
    else:
        price_col = loc_high_col
    qty_col = price_col + 1

    target_zone = "LOC평단" if price_col == loc_avg_col else "LOC고가"
    log(
        f"sheet_write symbol={msg.symbol} row={target_row} "
        f"zone={target_zone} price_col={col_to_a1(price_col)} qty_col={col_to_a1(qty_col)}"
    )

    ws.update(range_name=f"{col_to_a1(price_col)}{target_row}", values=[[msg.fill_price]])
    ws.update(range_name=f"{col_to_a1(qty_col)}{target_row}", values=[[msg.fill_qty]])
    return get_fill_result_for_row(ws, sh.title, target_row, total_qty_col, msg.symbol)


def process_upbit_fill_to_sheet(
    gc: gspread.Client,
    tz_name: str,
    worksheet_name: str,
    target_symbol: str,
    fill: UpbitFill,
    backup_dir: str,
    backup_cache: set,
    backup_context: str,
) -> Optional[FillResult]:
    if fill.side != "bid":
        return None
    sh = resolve_spreadsheet(gc, target_symbol)
    ensure_spreadsheet_backup_once(sh, backup_dir, backup_cache, backup_context, target_symbol)
    ws = sh.worksheet(worksheet_name) if worksheet_name else sh.get_worksheet(0)
    values = ws.get_all_values()
    header_row, date_col, loc_avg_col, loc_high_col = find_header_row_and_columns(values)
    total_qty_col = find_total_qty_column(values, header_row, loc_high_col)

    half_round_usd = get_numeric_cell_value(ws, "B3")
    avg_price = get_numeric_cell_value(ws, "R6")
    ratio_half = fill.amount / half_round_usd if half_round_usd > 0 else 0
    ratio_full = fill.amount / (half_round_usd * 2) if half_round_usd > 0 else 0
    log(
        f"upbit_ratio_check fill_id={fill.fill_id} amount={fill.amount:.4f} "
        f"b3={half_round_usd:.4f} ratio_half={ratio_half:.4f} ratio_full={ratio_full:.4f}"
    )

    if 0.8 <= ratio_full <= 1.2:
        target_date = fill.trade_time.date()
        target_date_text = target_date.strftime("%Y-%m-%d")
        target_row = find_or_create_date_row(ws, values, header_row, date_col, target_date, target_date_text)
        half_qty = fill.qty / 2.0
        log(
            f"upbit_sheet_write mode=both row={target_row} price={fill.price} qty_half={half_qty} "
            f"ratio_full={ratio_full:.4f}"
        )
        ws.update(range_name=f"{col_to_a1(loc_avg_col)}{target_row}", values=[[fill.price]])
        ws.update(range_name=f"{col_to_a1(loc_avg_col + 1)}{target_row}", values=[[half_qty]])
        ws.update(range_name=f"{col_to_a1(loc_high_col)}{target_row}", values=[[fill.price]])
        ws.update(range_name=f"{col_to_a1(loc_high_col + 1)}{target_row}", values=[[half_qty]])
    elif 0.8 <= ratio_half <= 1.2:
        target_date = fill.trade_time.date()
        target_date_text = target_date.strftime("%Y-%m-%d")
        target_row = find_or_create_date_row(ws, values, header_row, date_col, target_date, target_date_text)
        if fill.price > avg_price:
            price_col = loc_high_col
            zone = "LOC고가"
        else:
            price_col = loc_avg_col
            zone = "LOC평단"
        log(
            f"upbit_sheet_write mode=single row={target_row} zone={zone} price={fill.price} qty={fill.qty} "
            f"ratio_half={ratio_half:.4f}"
        )
        ws.update(range_name=f"{col_to_a1(price_col)}{target_row}", values=[[fill.price]])
        ws.update(range_name=f"{col_to_a1(price_col + 1)}{target_row}", values=[[fill.qty]])
    else:
        log(
            f"upbit_fill_skipped fill_id={fill.fill_id} amount={fill.amount:.4f} "
            f"ratio_half={ratio_half:.4f} ratio_full={ratio_full:.4f}"
        )
        return None

    return get_fill_result_for_row(ws, sh.title, target_row, total_qty_col, target_symbol)


def run_upbit_sync_once(
    gc: gspread.Client,
    state: Dict,
    tz_name: str,
    target_date: date,
    worksheet_name: str,
    upbit_access_key: str,
    upbit_secret_key: str,
    upbit_market: str,
    upbit_market_asset: str,
    upbit_sheet_symbol: str,
    upbit_base_url: str,
    upbit_orders_path: str,
    explicit_date: bool,
    backup_dir: str,
    backup_cache: set,
    backup_context: str,
) -> Tuple[int, int, Optional[FillResult]]:
    fills = fetch_upbit_fills_for_date(
        tz_name=tz_name,
        target_date=target_date,
        access_key=upbit_access_key,
        secret_key=upbit_secret_key,
        market_filter=upbit_market,
        market_asset_filter=upbit_market_asset,
        base_url=upbit_base_url,
        orders_path=upbit_orders_path,
    )
    processed_ids = set(state.get("processed_upbit_fill_ids", []))
    new_fills = fills if explicit_date else [f for f in fills if f.fill_id not in processed_ids]
    if new_fills:
        log(f"upbit_manual_sync_new_fills count={len(new_fills)} market={upbit_market}")

    processed_count = 0
    written_count = 0
    last_result: Optional[FillResult] = None
    for fill in sorted(new_fills, key=lambda x: x.trade_time):
        processed_count += 1
        result = process_upbit_fill_to_sheet(
            gc=gc,
            tz_name=tz_name,
            worksheet_name=worksheet_name,
            target_symbol=upbit_sheet_symbol,
            fill=fill,
            backup_dir=backup_dir,
            backup_cache=backup_cache,
            backup_context=backup_context,
        )
        processed_ids.add(fill.fill_id)
        if result:
            written_count += 1
            last_result = result

    state["processed_upbit_fill_ids"] = list(sorted(processed_ids))[-1000:]
    return processed_count, written_count, last_result


def load_state(path: Path) -> Dict:
    if not path.exists():
        return {"last_update_id": 0, "processed_upbit_fill_ids": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if "processed_upbit_fill_ids" not in data:
            data["processed_upbit_fill_ids"] = []
        return data
    except (json.JSONDecodeError, OSError):
        return {"last_update_id": 0, "processed_upbit_fill_ids": []}


def save_state(path: Path, state: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def get_update_text(update: Dict) -> Optional[str]:
    for key in ["message", "edited_message", "channel_post", "edited_channel_post"]:
        part = update.get(key) or {}
        text = part.get("text")
        if text:
            return text
    return None


def fetch_updates(token: str, offset: int, timeout: int) -> List[Dict]:
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    resp = requests.get(url, params={"offset": offset, "timeout": timeout}, timeout=timeout + 10)
    resp.raise_for_status()
    body = resp.json()
    if not body.get("ok"):
        raise RuntimeError(f"telegram error: {body}")
    return body.get("result", [])


def get_update_chat_id(update: Dict) -> Optional[int]:
    for key in ["message", "edited_message", "channel_post", "edited_channel_post"]:
        part = update.get(key) or {}
        chat = part.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is not None:
            return int(chat_id)
    return None


def send_telegram_message(token: str, chat_id: int, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=15)
    resp.raise_for_status()
    log(f"telegram_reply_sent chat_id={chat_id}")


def main() -> None:
    load_dotenv()

    tz_name = os.getenv("TIMEZONE", "Asia/Seoul")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    sa_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    worksheet_name = os.getenv("WORKSHEET_NAME", "").strip()
    poll_timeout = int(os.getenv("TELEGRAM_POLL_TIMEOUT", "30"))
    poll_interval = int(os.getenv("TELEGRAM_POLL_INTERVAL", "2"))
    state_file = Path(os.getenv("STATE_FILE", "/Users/test/AIassistant/state.json"))
    start_latest_first = os.getenv("START_FROM_LATEST_ON_FIRST_RUN", "true").lower().strip() in {
        "1",
        "true",
        "yes",
        "on",
    }

    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")
    if not sa_file:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_FILE is required")

    upbit_enabled = os.getenv("UPBIT_ENABLED", "false").lower().strip() in {"1", "true", "yes", "on"}
    upbit_access_key = os.getenv("UPBIT_ACCESS_KEY", "").strip()
    upbit_secret_key = os.getenv("UPBIT_SECRET_KEY", "").strip()
    upbit_market = os.getenv("UPBIT_MARKET", "KRW-BTC").strip()
    upbit_market_asset = os.getenv("UPBIT_MARKET_ASSET", "BTC").strip().upper()
    upbit_sheet_symbol = os.getenv("UPBIT_SHEET_SYMBOL", "BTC").strip().upper()
    upbit_base_url = os.getenv("UPBIT_BASE_URL", "https://api.upbit.com").strip()
    upbit_orders_path = os.getenv("UPBIT_ORDERS_PATH", "/v1/orders").strip()
    upbit_command_text = os.getenv("UPBIT_COMMAND_TEXT", "업비트 기록 수행").strip()
    backup_dir = os.getenv("SPREADSHEET_BACKUP_DIR", "/Users/test/AIassistant/spreadsheet_backups").strip()

    log("bot_start")
    gc = gspread.service_account(filename=sa_file)
    has_state = state_file.exists()
    state = load_state(state_file)
    offset = int(state.get("last_update_id", 0)) + 1

    if (not has_state) and start_latest_first:
        warmup = fetch_updates(token, 0, 0)
        if warmup:
            offset = max(int(x["update_id"]) for x in warmup) + 1
            state["last_update_id"] = offset - 1
            save_state(state_file, state)
            log(f"warmup_skip_old_updates count={len(warmup)} offset={offset}")

    while True:
        try:
            updates = fetch_updates(token, offset, poll_timeout)
            if updates:
                log(f"updates_received count={len(updates)}")
            for upd in updates:
                upd_id = int(upd["update_id"])
                backup_cache = set()
                try:
                    text = get_update_text(upd)
                    if text:
                        log(f"update_processing update_id={upd_id}")
                        chat_id = get_update_chat_id(upd)
                        if chat_id is not None:
                            state["default_chat_id"] = int(chat_id)

                        cmd_parsed = parse_upbit_command_date(text, upbit_command_text, tz_name)
                        if cmd_parsed is not None:
                            cmd_date, explicit_date = cmd_parsed
                            if not upbit_enabled:
                                if chat_id is not None:
                                    send_telegram_message(token, chat_id, "업비트 기능이 비활성화되어 있습니다. (UPBIT_ENABLED=false)")
                                log("upbit_command_ignored_disabled")
                            elif not upbit_access_key or not upbit_secret_key:
                                if chat_id is not None:
                                    send_telegram_message(token, chat_id, "업비트 API 키가 설정되지 않았습니다.")
                                log("upbit_command_ignored_missing_keys")
                            else:
                                processed_count, written_count, last_result = run_upbit_sync_once(
                                    gc=gc,
                                    state=state,
                                    tz_name=tz_name,
                                    target_date=cmd_date,
                                    worksheet_name=worksheet_name,
                                    upbit_access_key=upbit_access_key,
                                    upbit_secret_key=upbit_secret_key,
                                    upbit_market=upbit_market,
                                    upbit_market_asset=upbit_market_asset,
                                    upbit_sheet_symbol=upbit_sheet_symbol,
                                    upbit_base_url=upbit_base_url,
                                    upbit_orders_path=upbit_orders_path,
                                    explicit_date=explicit_date,
                                    backup_dir=backup_dir,
                                    backup_cache=backup_cache,
                                    backup_context=f"upbit_update_{upd_id}_{cmd_date.isoformat()}",
                                )
                                save_state(state_file, state)
                                if chat_id is not None:
                                    send_telegram_message(
                                        token,
                                        chat_id,
                                        build_upbit_command_result_text(processed_count, written_count, last_result),
                                    )
                                log(
                                    f"upbit_command_done date={cmd_date.isoformat()} processed={processed_count} written={written_count}"
                                )
                            offset = max(offset, upd_id + 1)
                            continue

                        msg = parse_fill_message(text, tz_name)
                        if msg:
                            log(
                                f"fill_message_parsed update_id={upd_id} symbol={msg.symbol} "
                                f"side={msg.trade_side} price={msg.fill_price} qty={msg.fill_qty}"
                            )
                            result = process_fill_to_sheet(
                                gc,
                                msg,
                                tz_name,
                                worksheet_name,
                                backup_dir=backup_dir,
                                backup_cache=backup_cache,
                                backup_context=f"meritz_update_{upd_id}",
                            )
                            if result:
                                if chat_id is not None:
                                    send_telegram_message(token, chat_id, build_reply_text(result))
                            log(f"processed update_id={upd_id} symbol={msg.symbol}")
                except Exception as per_update_error:
                    log(
                        f"error(update_id={upd_id}): "
                        f"{per_update_error.__class__.__name__}: {repr(per_update_error)}"
                    )
                    log(traceback.format_exc(limit=3).strip())
                offset = max(offset, upd_id + 1)

            state["last_update_id"] = offset - 1
            save_state(state_file, state)
        except Exception as e:
            log(f"error: {e}")
            time.sleep(max(3, poll_interval))
            continue

        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
