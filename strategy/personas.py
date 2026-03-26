"""
Trading Personas
================
Setiap persona merepresentasikan gaya trading tokoh legendaris.
Parameter disesuaikan dengan filosofi dan karakter masing-masing.
"""

PERSONAS = {

    "warren_buffett": {
        "id":          "warren_buffett",
        "name":        "Warren Buffett",
        "title":       "The Oracle of Omaha",
        "emoji":       "🎩",
        "style":       "Value & Extreme Patience",
        "description": "Hanya masuk saat harga sangat murah. Sabar menunggu setup sempurna. Tidak rakus, tidak panik.",
        "quote":       "Be fearful when others are greedy, greedy when others are fearful.",
        "risk_level":  1,  # 1-5
        "timeframe":   "4h",
        "bb_period":   50,      # sangat panjang = lebih selektif
        "bb_std":      2.5,     # band lebar = entry hanya di ekstrem
        "leverage":    2,
        "tp_pct":      4.0,     # target besar, sabar
        "sl_pct":      1.0,     # stop loss ketat
        "adx_max":     20,      # hanya ranging/sideways
        "vol_spike":   1.5,
        "confirm_candles": 2,   # tunggu 2 candle konfirmasi
        "max_trades":  1,
        "dca":         False,
        "color":       "#f59e0b",
    },

    "paul_tudor_jones": {
        "id":          "paul_tudor_jones",
        "name":        "Paul Tudor Jones",
        "title":       "The Macro Wizard",
        "emoji":       "📈",
        "style":       "Macro Trend Following",
        "description": "Ikuti trend besar. Potong kerugian cepat tanpa ampun. Biarkan profit berjalan.",
        "quote":       "Losers average losers. The most important rule is to play great defense.",
        "risk_level":  3,
        "timeframe":   "1h",
        "bb_period":   20,
        "bb_std":      2.0,
        "leverage":    5,
        "tp_pct":      3.0,
        "sl_pct":      1.0,     # SL ketat = disiplin tinggi
        "adx_max":     35,      # toleran dengan trending market
        "vol_spike":   2.5,
        "confirm_candles": 1,
        "max_trades":  2,
        "dca":         False,
        "color":       "#3b82f6",
    },

    "ray_dalio": {
        "id":          "ray_dalio",
        "name":        "Ray Dalio",
        "title":       "The All Weather Master",
        "emoji":       "☯️",
        "style":       "Balanced & Diversified",
        "description": "Portofolio seimbang di segala kondisi market. Tidak ada kondisi yang bisa memusnahkan.",
        "quote":       "Diversification is the holy grail of investing.",
        "risk_level":  2,
        "timeframe":   "4h",
        "bb_period":   30,
        "bb_std":      2.0,
        "leverage":    3,
        "tp_pct":      2.5,
        "sl_pct":      1.0,
        "adx_max":     25,
        "vol_spike":   2.0,
        "confirm_candles": 2,
        "max_trades":  3,       # diversifikasi beberapa posisi
        "dca":         False,
        "color":       "#8b5cf6",
    },

    "george_soros": {
        "id":          "george_soros",
        "name":        "George Soros",
        "title":       "The Man Who Broke the Bank",
        "emoji":       "🦁",
        "style":       "Reflexivity & Concentrated Bets",
        "description": "Bet besar saat yakin. Manfaatkan momentum dan sentimen pasar. High risk, high reward.",
        "quote":       "It's not whether you're right or wrong, but how much you make when right.",
        "risk_level":  5,
        "timeframe":   "1h",
        "bb_period":   20,
        "bb_std":      1.8,     # band lebih sempit = lebih sering entry
        "leverage":    10,
        "tp_pct":      5.0,
        "sl_pct":      2.0,
        "adx_max":     40,
        "vol_spike":   3.0,
        "confirm_candles": 1,
        "max_trades":  2,
        "dca":         False,
        "color":       "#ef4444",
    },

    "michael_burry": {
        "id":          "michael_burry",
        "name":        "Michael Burry",
        "title":       "The Big Short",
        "emoji":       "🐻",
        "style":       "Contrarian & Deep Value",
        "description": "Lawan arah market saat semua orang serakah. Short saat overbought ekstrem.",
        "quote":       "I'm going short on the entire housing market. Everyone thinks I'm crazy.",
        "risk_level":  4,
        "timeframe":   "4h",
        "bb_period":   20,
        "bb_std":      2.2,
        "leverage":    7,
        "tp_pct":      4.0,
        "sl_pct":      1.5,
        "adx_max":     30,
        "vol_spike":   2.0,
        "prefer_short": True,   # bias ke SHORT / contrarian
        "confirm_candles": 2,
        "max_trades":  2,
        "dca":         False,
        "color":       "#6b7280",
    },

    "bill_ackman": {
        "id":          "bill_ackman",
        "name":        "Bill Ackman",
        "title":       "The Activist Investor",
        "emoji":       "💼",
        "style":       "High Conviction Concentrated",
        "description": "Analisis mendalam, keyakinan tinggi, posisi besar. Tidak setengah-setengah.",
        "quote":       "We only invest in things we deeply understand.",
        "risk_level":  4,
        "timeframe":   "4h",
        "bb_period":   25,
        "bb_std":      2.0,
        "leverage":    8,
        "tp_pct":      6.0,     # target sangat besar
        "sl_pct":      2.0,
        "adx_max":     25,
        "vol_spike":   2.0,
        "confirm_candles": 3,   # sangat selektif
        "max_trades":  1,       # concentrated = 1 posisi saja
        "dca":         False,
        "color":       "#0ea5e9",
    },

    "li_ka_shing": {
        "id":          "li_ka_shing",
        "name":        "Li Ka-Shing",
        "title":       "Superman of Asia",
        "emoji":       "🐉",
        "style":       "Long-term Value Asia Style",
        "description": "Sabar menunggu harga diskon besar. Fokus pada aset berkualitas dengan harga murah.",
        "quote":       "I buy when others are selling, sell when others are buying.",
        "risk_level":  2,
        "timeframe":   "4h",
        "bb_period":   40,
        "bb_std":      2.5,
        "leverage":    3,
        "tp_pct":      3.0,
        "sl_pct":      1.0,
        "adx_max":     20,
        "vol_spike":   1.8,
        "confirm_candles": 2,
        "max_trades":  2,
        "dca":         True,    # DCA saat harga turun
        "color":       "#f97316",
    },

    "naruto": {
        "id":          "naruto",
        "name":        "Naruto Uzumaki",
        "title":       "The Never Give Up Trader",
        "emoji":       "🍥",
        "style":       "Aggressive DCA & Persistence",
        "description": "Tidak pernah menyerah! Terus averaging down. Keyakinan penuh bahwa harga akan kembali.",
        "quote":       "Dattebayo! Aku tidak akan menyerah sampai profit!",
        "risk_level":  3,
        "timeframe":   "15m",
        "bb_period":   20,
        "bb_std":      2.0,
        "leverage":    3,
        "tp_pct":      2.0,
        "sl_pct":      3.0,     # SL lebar = tidak mudah kena stop
        "adx_max":     30,
        "vol_spike":   2.5,
        "confirm_candles": 1,
        "max_trades":  3,
        "dca":         True,    # DCA = averaging down
        "color":       "#f59e0b",
    },

    "tom_lee": {
        "id":          "tom_lee",
        "name":        "Tom Lee",
        "title":       "The Eternal Bull",
        "emoji":       "🐂",
        "style":       "Bullish Bias & Buy the Dip",
        "description": "Selalu optimis. Beli setiap dip. BTC selalu naik jangka panjang.",
        "quote":       "Bitcoin will reach $X by end of year. Buy the dip!",
        "risk_level":  3,
        "timeframe":   "1h",
        "bb_period":   20,
        "bb_std":      2.0,
        "leverage":    5,
        "tp_pct":      3.0,
        "sl_pct":      1.5,
        "adx_max":     30,
        "vol_spike":   2.0,
        "prefer_long": True,    # hanya LONG, tidak short
        "confirm_candles": 1,
        "max_trades":  2,
        "dca":         True,
        "color":       "#22c55e",
    },

    "custom": {
        "id":          "custom",
        "name":        "Custom Strategy",
        "title":       "Your Own Style",
        "emoji":       "⚙️",
        "style":       "Fully Customizable",
        "description": "Atur semua parameter sesuai keinginan kamu sendiri.",
        "quote":       "Your strategy, your rules.",
        "risk_level":  3,
        "timeframe":   "1h",
        "bb_period":   20,
        "bb_std":      2.0,
        "leverage":    5,
        "tp_pct":      2.0,
        "sl_pct":      1.0,
        "adx_max":     25,
        "vol_spike":   2.0,
        "confirm_candles": 1,
        "max_trades":  2,
        "dca":         False,
        "color":       "#a855f7",
    },
}


def get_persona(persona_id: str) -> dict:
    return PERSONAS.get(persona_id, PERSONAS["warren_buffett"])


def list_personas() -> list:
    return list(PERSONAS.values())
