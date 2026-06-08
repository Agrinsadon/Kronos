"""
trader.py — Aggressiivinen strategia: 500€ → 5000€
- Skannaa S&P 500 + Nasdaq 100 automaattisesti
- Priorisoi volatiilit osakkeet (enemmän liikettä)
- Nopea osto/myynti sykli
"""

import json
import csv
import os
import time
import random
from datetime import datetime, date, timedelta
import yfinance as yf
import pandas as pd
import numpy as np
import torch

from config import (
    STARTING_BALANCE, TRADE_ALLOCATION,
    BUY_THRESHOLD, SELL_THRESHOLD,
    STOP_LOSS, TAKE_PROFIT,
    LOOKBACK, PRED_LEN,
    KRONOS_MODEL, KRONOS_TOKENIZER, DEVICE,
    STATE_FILE, LOG_FILE, UNIVERSE_CACHE,
    MIN_PRICE, MIN_VOLUME_USD, MAX_SCAN, MAX_POSITIONS,
    PREFER_VOLATILE, MIN_VOLATILITY
)


# ── Kronos lataus ──────────────────────────────────────────────────────────────

_predictor = None

def get_predictor():
    global _predictor
    if _predictor is None:
        print("⏳ Ladataan Kronos-malli...")
        from model import Kronos, KronosTokenizer, KronosPredictor
        tokenizer = KronosTokenizer.from_pretrained(KRONOS_TOKENIZER)
        model = Kronos.from_pretrained(KRONOS_MODEL)
        device = DEVICE if torch.backends.mps.is_available() else "cpu"
        _predictor = KronosPredictor(model, tokenizer, max_context=512, device=device)
        print(f"✅ Kronos ladattu — laite: {device}")
    return _predictor


# ── Osakeuniversumi ────────────────────────────────────────────────────────────

def fetch_sp500_symbols() -> list[str]:
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
        symbols = tables[0]["Symbol"].tolist()
        return [s.replace(".", "-") for s in symbols]
    except:
        return []

def fetch_nasdaq100_symbols() -> list[str]:
    try:
        tables = pd.read_html("https://en.wikipedia.org/wiki/Nasdaq-100")
        for t in tables:
            cols = [c.lower() for c in t.columns]
            if "ticker" in cols:
                col = t.columns[[c.lower() == "ticker" for c in t.columns][0] if any(c.lower() == "ticker" for c in t.columns) else 0]
                return [str(s) for s in t[col].dropna().tolist()]
    except:
        pass
    return []

def load_universe() -> list[str]:
    if os.path.exists(UNIVERSE_CACHE):
        with open(UNIVERSE_CACHE) as f:
            cache = json.load(f)
        if datetime.now() - datetime.fromisoformat(cache["date"]) < timedelta(days=7):
            print(f"📋 Universumi välimuistista: {len(cache['symbols'])} symbolia")
            return cache["symbols"]

    print("🌐 Haetaan S&P 500 + Nasdaq 100...")
    all_symbols = list(set(fetch_sp500_symbols() + fetch_nasdaq100_symbols()))
    all_symbols.sort()
    with open(UNIVERSE_CACHE, "w") as f:
        json.dump({"date": datetime.now().isoformat(), "symbols": all_symbols}, f)
    print(f"✅ {len(all_symbols)} symbolia haettu")
    return all_symbols


def get_stock_metrics(symbol: str) -> dict | None:
    """
    Hae osakkeen tärkeimmät mittarit yhdellä haulla:
    hinta, volyymi, volatiliteetti, momentum.
    """
    try:
        df = yf.Ticker(symbol).history(period="30d")
        if df.empty or len(df) < 5:
            return None

        closes = df["Close"]
        volumes = df["Volume"]
        last_price = float(closes.iloc[-1])
        avg_vol_usd = float((closes * volumes).mean())

        # Päivätuottojen keskihajonta = volatiliteetti
        daily_returns = closes.pct_change().dropna()
        volatility = float(daily_returns.std())

        # 5 päivän momentum (onko trendi nouseva?)
        momentum_5d = float((closes.iloc[-1] - closes.iloc[-5]) / closes.iloc[-5])

        return {
            "price": last_price,
            "avg_vol_usd": avg_vol_usd,
            "volatility": volatility,
            "momentum_5d": momentum_5d,
        }
    except:
        return None


def filter_and_rank_universe(symbols: list[str], already_owned: list[str]) -> list[str]:
    """
    Suodata + järjestä osakkeet volatiliteetin mukaan.
    Volatiilit osakkeet priorisoidaan — enemmän liikettä = enemmän mahdollisuuksia.
    """
    print(f"🔍 Analysoidaan {len(symbols)} osaketta...")
    scored = []
    available = [s for s in symbols if s not in already_owned]
    random.shuffle(available)
    # Tarkista max 300 osaketta kerralla jotta ei kestä ikuisuutta
    check_pool = available[:300]

    batch_size = 50
    for i in range(0, len(check_pool), batch_size):
        batch = check_pool[i:i+batch_size]
        try:
            raw = yf.download(
                batch, period="30d",
                group_by="ticker", auto_adjust=True,
                progress=False, threads=True,
            )
            for sym in batch:
                try:
                    if len(batch) == 1:
                        closes = raw["Close"].dropna()
                        volumes = raw["Volume"].dropna()
                    else:
                        closes = raw[sym]["Close"].dropna()
                        volumes = raw[sym]["Volume"].dropna()

                    if closes.empty or len(closes) < 5:
                        continue

                    last_price = float(closes.iloc[-1])
                    avg_vol_usd = float((closes * volumes).mean())
                    daily_returns = closes.pct_change().dropna()
                    volatility = float(daily_returns.std())
                    momentum = float((closes.iloc[-1] - closes.iloc[-5]) / closes.iloc[-5])

                    # Perussuodatus
                    if last_price < MIN_PRICE or avg_vol_usd < MIN_VOLUME_USD:
                        continue
                    if PREFER_VOLATILE and volatility < MIN_VOLATILITY:
                        continue

                    # Pisteytetään: korkea volatiliteetti + positiivinen momentum = hyvä kandidaatti
                    score = volatility * 0.6 + max(momentum, 0) * 0.4
                    scored.append((sym, score))

                except Exception:
                    continue
        except Exception as e:
            print(f"   Erä virhe: {e}")
        time.sleep(0.3)

    # Järjestä parhaan pisteytyken mukaan
    scored.sort(key=lambda x: x[1], reverse=True)
    result = [sym for sym, _ in scored[:MAX_SCAN]]
    print(f"✅ {len(result)} osaketta skannaukseen (volatiliteettijärjestyksessä)")
    return result


# ── Data + ennustus ────────────────────────────────────────────────────────────

def fetch_data(symbol: str) -> pd.DataFrame | None:
    try:
        df = yf.Ticker(symbol).history(period=f"{LOOKBACK + 10}d")
        if df.empty or len(df) < 10:
            return None
        df = df.rename(columns={"Open":"open","High":"high","Low":"low","Close":"close","Volume":"volume"})
        df["amount"] = df["close"] * df["volume"]
        df = df[["open","high","low","close","volume","amount"]].tail(LOOKBACK).reset_index()
        df = df.rename(columns={"Date":"timestamps","Datetime":"timestamps"})
        df["timestamps"] = pd.to_datetime(df["timestamps"]).dt.tz_localize(None)
        return df
    except:
        return None


def predict_return(symbol: str) -> float | None:
    df = fetch_data(symbol)
    if df is None:
        return None
    try:
        predictor = get_predictor()
        x_df = df[["open","high","low","close","volume","amount"]]
        x_ts = df["timestamps"]
        last_ts = df["timestamps"].iloc[-1]
        y_ts = pd.Series(pd.bdate_range(start=last_ts + pd.Timedelta(days=1), periods=PRED_LEN))

        pred_df = predictor.predict(
            df=x_df, x_timestamp=x_ts, y_timestamp=y_ts,
            pred_len=PRED_LEN, T=0.8, top_p=0.9, sample_count=3,
        )
        current = df["close"].iloc[-1]
        predicted = pred_df["close"].iloc[0]
        return float((predicted - current) / current)
    except:
        return None


def scan_candidates(candidates: list[str]) -> list[tuple[str, float]]:
    """Skannaa kaikki kandidaatit Kronos-ennustuksella."""
    results = []
    total = len(candidates)
    print(f"\n🤖 Kronos skannaa {total} osaketta...")
    for i, sym in enumerate(candidates, 1):
        ret = predict_return(sym)
        if ret is not None:
            results.append((sym, ret))
            marker = "🟢" if ret >= BUY_THRESHOLD else ("🔴" if ret < 0 else "🟡")
            print(f"   [{i}/{total}] {sym}: {ret*100:+.2f}% {marker}")
    results.sort(key=lambda x: x[1], reverse=True)
    return results


# ── Portfolio ──────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "cash": STARTING_BALANCE,
        "positions": {},
        "total_trades": 0,
        "winning_trades": 0,
        "start_date": str(date.today()),
        "peak_value": STARTING_BALANCE,
    }

def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def get_current_price(symbol: str) -> float | None:
    try:
        hist = yf.Ticker(symbol).history(period="1d")
        return float(hist["Close"].iloc[-1]) if not hist.empty else None
    except:
        return None

def portfolio_value(state: dict) -> float:
    total = state["cash"]
    for sym, pos in state["positions"].items():
        price = get_current_price(sym)
        if price:
            total += pos["shares"] * price
    return total

def log_trade(action, symbol, shares, price, pnl, balance):
    exists = os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(["date","action","symbol","shares","price","pnl","balance"])
        w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M"), action, symbol,
                    round(shares,4), round(price,2), round(pnl,2), round(balance,2)])


# ── Pääsykli ───────────────────────────────────────────────────────────────────

def run_trading_cycle() -> dict:
    state = load_state()
    actions = []

    print(f"\n{'='*55}")
    print(f"🚀 AGGRESSIIVINEN SYKLI: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    pv = portfolio_value(state)
    print(f"💰 Käteinen: {state['cash']:.2f}€ | Portfolio: {pv:.2f}€")
    print(f"🎯 Tavoite: 5000€ | Edistyminen: {pv/5000*100:.1f}%")
    print(f"{'='*55}")

    # ── 1. Universumi + suodatus ───────────────────────────────────────────────
    universe = load_universe()
    already_owned = list(state["positions"].keys())
    ranked_candidates = filter_and_rank_universe(universe, already_owned)

    # ── 2. Tarkista olemassaolevat positiot ───────────────────────────────────
    for symbol in list(state["positions"].keys()):
        pos = state["positions"][symbol]
        current_price = get_current_price(symbol)
        if not current_price:
            continue

        pnl_pct = (current_price - pos["buy_price"]) / pos["buy_price"]
        pred = predict_return(symbol)

        should_sell = False
        reason = ""

        if pnl_pct <= STOP_LOSS:
            should_sell, reason = True, f"🛑 Stop-loss ({pnl_pct*100:.1f}%)"
        elif pnl_pct >= TAKE_PROFIT:
            should_sell, reason = True, f"🎯 Take-profit ({pnl_pct*100:.1f}%)"
        elif pred is not None and pred <= SELL_THRESHOLD:
            should_sell, reason = True, f"📉 Trendi kääntyy ({pred*100:.1f}%)"

        if should_sell:
            proceeds = pos["shares"] * current_price
            pnl_eur = proceeds - (pos["shares"] * pos["buy_price"])
            state["cash"] += proceeds
            state["total_trades"] += 1
            if pnl_eur > 0:
                state["winning_trades"] += 1
            log_trade("MYYNTI", symbol, pos["shares"], current_price, pnl_eur, state["cash"])
            del state["positions"][symbol]

            emoji = "✅" if pnl_eur > 0 else "❌"
            actions.append(
                f"📤 MYYNTI: {symbol} {emoji}\n"
                f"   Syy: {reason}\n"
                f"   PnL: {'+' if pnl_eur>0 else ''}{pnl_eur:.2f}€ ({pnl_pct*100:+.1f}%)\n"
                f"   Kassassa: {state['cash']:.2f}€"
            )

    # ── 3. Osta uudet positiot ─────────────────────────────────────────────────
    open_slots = MAX_POSITIONS - len(state["positions"])

    if open_slots > 0 and state["cash"] > 10:
        scan_results = scan_candidates(ranked_candidates)
        top_picks = [(s, r) for s, r in scan_results if r >= BUY_THRESHOLD]
        buy_count = min(open_slots, len(top_picks))

        if buy_count > 0:
            cash_per_trade = (state["cash"] * TRADE_ALLOCATION) / buy_count
            print(f"\n💸 Ostetaan {buy_count} osaketta, {cash_per_trade:.2f}€ per positio")

            for symbol, pred_ret in top_picks[:buy_count]:
                price = get_current_price(symbol)
                if not price:
                    continue
                shares = cash_per_trade / price
                cost = shares * price
                state["cash"] -= cost
                state["positions"][symbol] = {
                    "shares": shares,
                    "buy_price": price,
                    "buy_date": str(date.today()),
                    "predicted_return": round(pred_ret * 100, 2),
                }
                log_trade("OSTO", symbol, shares, price, 0, state["cash"])
                actions.append(
                    f"📥 OSTO: {symbol}\n"
                    f"   Kronos ennuste: {pred_ret*100:+.2f}%\n"
                    f"   Hinta: {price:.2f}$\n"
                    f"   Sijoitettu: {cost:.2f}€"
                )

        # Top 5 yhteenveto Telegramiin
        top5_lines = ["📊 Päivän top skannaus:"]
        for sym, ret in scan_results[:5]:
            icon = "🟢" if ret >= BUY_THRESHOLD else "⚪"
            top5_lines.append(f"   {icon} {sym}: {ret*100:+.2f}%")
        actions.append("\n".join(top5_lines))

    # ── 4. Päivitä huippuarvo ──────────────────────────────────────────────────
    new_pv = portfolio_value(state)
    state["peak_value"] = max(state.get("peak_value", STARTING_BALANCE), new_pv)
    save_state(state)

    total_ret = (new_pv - STARTING_BALANCE) / STARTING_BALANCE * 100
    days_active = (date.today() - date.fromisoformat(state["start_date"])).days or 1
    daily_rate = total_ret / days_active
    days_to_goal = (
        int((np.log(5000/new_pv) / np.log(1 + daily_rate/100)))
        if daily_rate > 0 else 999
    )

    return {
        "actions": actions,
        "summary": {
            "portfolio_value": new_pv,
            "cash": state["cash"],
            "positions": list(state["positions"].keys()),
            "total_return_pct": total_ret,
            "progress_to_goal_pct": new_pv / 5000 * 100,
            "total_trades": state["total_trades"],
            "win_rate": (state["winning_trades"] / state["total_trades"] * 100) if state["total_trades"] > 0 else 0,
            "start_date": state["start_date"],
            "peak_value": state["peak_value"],
            "daily_rate": daily_rate,
            "days_to_goal_estimate": days_to_goal,
            "universe_size": len(universe),
        }
    }