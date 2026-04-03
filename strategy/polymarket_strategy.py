"""
Polymarket Mispricing Strategy
===============================
Strategi:
1. Arbitrage  : YES + NO < 97% → beli keduanya, profit dijamin
2. Near-cert  : Salah satu outcome > 95% harga, beli yang hampir pasti menang
3. Value bet  : Volume tinggi + harga sangat ekstrem (crowd wisdom)
"""

PLATFORM_FEE = 0.02   # 2% fee Polymarket per sisi
MIN_ARBT_GAP = 0.03   # minimum gap setelah fee untuk arbitrage
MIN_CONFIDENCE = 0.95  # minimum probabilitas untuk near-cert bet


def analyze_markets(markets: list, min_bet: float = 1.0, max_bet: float = 50.0) -> list:
    """
    Scan semua market dan return peluang diurutkan dari profit terbesar.
    markets: output dari PolymarketClient.get_popular_markets()
    """
    opportunities = []

    for m in markets:
        yes_p = m.get("yes_price", 0) / 100   # konversi % → desimal
        no_p  = m.get("no_price", 0) / 100
        vol   = m.get("volume_24h", 0)
        q     = m.get("question", "")

        if yes_p <= 0 or no_p <= 0:
            continue
        if not m.get("yes_token_id") or not m.get("no_token_id"):
            continue

        total = yes_p + no_p

        # ── Strategi 1: Arbitrage ──────────────────────────────────────────
        # Jika YES + NO < 97%, beli keduanya → profit guaranteed
        gap = 1.0 - total
        if gap >= MIN_ARBT_GAP:
            profit_pct = round(gap * 100, 2)
            # Ukuran bet: bagi rata antara YES dan NO
            bet_yes = round(min(max_bet / 2, max(min_bet, vol / 10000)), 2)
            bet_no  = bet_yes
            opportunities.append({
                "strategy":       "arbitrage",
                "market":         q,
                "condition_id":   m.get("condition_id", ""),
                "yes_token_id":   m.get("yes_token_id", ""),
                "no_token_id":    m.get("no_token_id", ""),
                "yes_price":      yes_p,
                "no_price":       no_p,
                "total":          round(total * 100, 1),
                "expected_profit_pct": profit_pct,
                "bet_yes_usdc":   bet_yes,
                "bet_no_usdc":    bet_no,
                "volume_24h":     vol,
                "action":         "BUY_BOTH",
                "reason":         f"YES({yes_p*100:.1f}%) + NO({no_p*100:.1f}%) = {total*100:.1f}% < 97%",
            })

        # ── Strategi 2: Near-certain outcome ──────────────────────────────
        # Salah satu outcome hampir pasti (>95%), beli yang hampir pasti
        # Hanya kalau volume cukup (crowd sudah ramai, harga reliable)
        if vol >= 50_000:
            if yes_p >= MIN_CONFIDENCE and yes_p < 0.995:
                bet = round(min(max_bet, max(min_bet, vol / 20000)), 2)
                opportunities.append({
                    "strategy":            "near_certain",
                    "market":              q,
                    "condition_id":        m.get("condition_id", ""),
                    "yes_token_id":        m.get("yes_token_id", ""),
                    "no_token_id":         m.get("no_token_id", ""),
                    "yes_price":           yes_p,
                    "no_price":            no_p,
                    "total":               round(total * 100, 1),
                    "expected_profit_pct": round((1 - yes_p) * 100, 2),
                    "bet_yes_usdc":        bet,
                    "bet_no_usdc":         0,
                    "volume_24h":          vol,
                    "action":              "BUY_YES",
                    "reason":              f"YES hampir pasti ({yes_p*100:.1f}%), vol=${vol/1000:.0f}k",
                })
            elif no_p >= MIN_CONFIDENCE and no_p < 0.995:
                bet = round(min(max_bet, max(min_bet, vol / 20000)), 2)
                opportunities.append({
                    "strategy":            "near_certain",
                    "market":              q,
                    "condition_id":        m.get("condition_id", ""),
                    "yes_token_id":        m.get("yes_token_id", ""),
                    "no_token_id":         m.get("no_token_id", ""),
                    "yes_price":           yes_p,
                    "no_price":            no_p,
                    "total":               round(total * 100, 1),
                    "expected_profit_pct": round((1 - no_p) * 100, 2),
                    "bet_yes_usdc":        0,
                    "bet_no_usdc":         bet,
                    "volume_24h":          vol,
                    "action":              "BUY_NO",
                    "reason":              f"NO hampir pasti ({no_p*100:.1f}%), vol=${vol/1000:.0f}k",
                })

    # Urutkan dari profit terbesar
    opportunities.sort(key=lambda x: x["expected_profit_pct"], reverse=True)
    return opportunities
