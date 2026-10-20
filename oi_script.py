import os, time, requests
from datetime import datetime, date, timedelta
import calendar

TG_TOKEN   = os.environ.get("TG_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")

MON, TUE, WED, THU, FRI = 0, 1, 2, 3, 4

def fetch_via_proxy(url):
    # This is a free proxy tunnel that NSE/BSE do not block
    proxy_url = "https://api.allorigins.win/raw?url=" + requests.utils.quote(url, safe='')
    try:
        r = requests.get(proxy_url, timeout=20)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"Proxy error: {e}")
    return None

def last_weekday_of_month(year, month, weekday):
    last_day = calendar.monthrange(year, month)[1]
    d = date(year, month, last_day)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d

def nearest_monthly_expiry(today, weekday):
    exp = last_weekday_of_month(today.year, today.month, weekday)
    if exp < today:
        y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        exp = last_weekday_of_month(y, m, weekday)
    return exp

def nearest_weekly_expiry(today, weekday):
    delta = (weekday - today.weekday()) % 7
    return today + timedelta(days=delta)

def pick_expiry(available, target_date):
    parsed = []
    for e in available:
        if not e: continue
        for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                parsed.append((datetime.strptime(str(e), fmt).date(), str(e)))
                break
            except Exception:
                continue
    if not parsed: return None
    parsed.sort()
    for dt, raw in parsed:
        if dt >= target_date: return raw
    return parsed[0][1]

def nse_oi(symbol, expiry_rule):
    url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    j = fetch_via_proxy(url)
    if not j or "records" not in j: return None
    
    try:
        expiries = j["records"].get("expiryDates", [])
        if not expiries: return None
        today = date.today()
        kind, wd = expiry_rule
        target = nearest_weekly_expiry(today, wd) if kind == "weekly" else nearest_monthly_expiry(today, wd)
        chosen = pick_expiry(expiries, target)
        if not chosen: return None
        calls, puts = {}, {}
        for row in j["records"]["data"]:
            if str(row.get("expiryDate")) != chosen: continue
            k = row.get("strikePrice")
            ce = row.get("CE", {}).get("openInterest", 0) or 0
            pe = row.get("PE", {}).get("openInterest", 0) or 0
            if k is None: continue
            if ce: calls[k] = ce
            if pe: puts[k] = pe
        if not calls or not puts: return None
        return (max(calls, key=calls.get), max(puts, key=puts.get), chosen)
    except Exception as e:
        print(f"NSE {symbol} parse error: {e}")
        return None

def sensex_oi():
    # Get expiry list
    exp_url = "https://api.bseindia.com/BseIndiaAPI/api/DerivExpiry/w?Scrip_cd=1&Type=IO"
    exp_json = fetch_via_proxy(exp_url)
    expiries_raw = []
    if exp_json:
        expiries_raw = [x.get("Expiry_Date") if isinstance(x, dict) else x for x in (exp_json if isinstance(exp_json, list) else exp_json.get("Table", []))]
    
    today = date.today()
    chosen_exp = pick_expiry(expiries_raw, nearest_monthly_expiry(today, THU)) or ""
    
    url = f"https://api.bseindia.com/BseIndiaAPI/api/DerivOptionChain/w?Scrip_cd=1&Expiry={chosen_exp}"
    j = fetch_via_proxy(url)
    if not j or "Table" not in j: return None
    
    try:
        calls, puts = {}, {}
        for row in j["Table"]:
            k = row.get("Strike_Price")
            co, po = row.get("C_Open_Int", 0) or 0, row.get("P_Open_Int", 0) or 0
            if k is None: continue
            if co: calls[k] = co
            if po: puts[k] = po
        if not calls or not puts: return None
        return (max(calls, key=calls.get), max(puts, key=puts.get), chosen_exp or "NA")
    except Exception as e: 
        print(f"BSE parse error: {e}")
        return None

def mcx_oi(commodity):
    url = f"https://priceapi.moneycontrol.com/pricefeed/commodity/option/chain?symbol={commodity}&expiry=near"
    j = fetch_via_proxy(url)
    if not j or "data" not in j: return None
    
    try:
        calls, puts = {}, {}
        for row in j.get("data", {}).get("optionChain", []):
            k = row.get("strikePrice")
            co, po = row.get("callOi", 0) or 0, row.get("putOi", 0) or 0
            if k is None: continue
            if co: calls[k] = co
            if po: puts[k] = po
        if not calls or not puts: return None
        return (max(calls, key=calls.get), max(puts, key=puts.get), "near-month")
    except Exception as e: 
        print(f"MCX {commodity} parse error: {e}")
        return None

def pair(p): return f"{p[0]},{p[1]}" if p else "NA,NA"

def build_line():
    res, exps = {}, {}
    
    for sym, rule in [("NIFTY", ("weekly", TUE)), ("BANKNIFTY", ("monthly", TUE)), ("FINNIFTY", ("monthly", TUE)), ("MIDCPNIFTY", ("monthly", TUE))]:
        out = nse_oi(sym, rule)
        res[sym], exps[sym] = pair(out), out[2] if out else "NA"
        time.sleep(1)

    out = sensex_oi()
    res["SENSEX"], exps["SENSEX"] = pair(out), out[2] if out else "NA"
    
    for sym in ["CRUDEOIL", "NATURALGAS", "GOLD"]:
        out = mcx_oi(sym)
        res[sym], exps[sym] = pair(out), out[2] if out else "NA"
        time.sleep(1)
        
    line = f"{datetime.now().strftime('%d-%m-%Y')}|NIFTY:{res['NIFTY']}|BANKNIFTY:{res['BANKNIFTY']}|SENSEX:{res['SENSEX']}|FINNIFTY:{res['FINNIFTY']}|MIDCPNIFTY:{res['MIDCPNIFTY']}|CRUDEOIL:{res['CRUDEOIL']}|NATURALGAS:{res['NATURALGAS']}|GOLD:{res['GOLD']}|"
    exp_line = "Expiries used -> " + " | ".join(f"{k}:{v}" for k, v in exps.items())
    return line, exp_line

def send_telegram(msg):
    if not TG_TOKEN or not TG_CHAT_ID: return
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data={"chat_id": TG_CHAT_ID, "text": f"```\n{msg}\n```", "parse_mode": "Markdown"}, timeout=10)
    except Exception: pass

if __name__ == "__main__":
    line, exp_line = build_line()
    print(line)
    send_telegram(line + "\n\n" + exp_line)
