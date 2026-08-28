"""
Synthetic dataset generator faithful to Corporación Favorita
============================================================
Produces the 6 tables from the Kaggle competition with the SAME column names
and types, and with the same embedded signals the analysis sets out to find. This way the pipeline (dbt + notebooks + models) actually runs, and
the day you download the real Kaggle CSV everything works without changing a line
because the schema is identical.

Embedded signals (deliberate, so the EDA can find them):
  - Weekly seasonality: weekends higher than weekdays.
  - Mild annual seasonality: December high (holidays).
  - Payday effect: spike around the 15th and month-end (Ecuadorian pay cycle).
  - Promo lift: onpromotion multiplies sales (varies by family).
  - Oil correlation: high oil -> slightly higher macro demand.
  - Earthquake shock 2016-04-16: water/supplies spike for ~2 weeks.
  - Perishables: lower mean and more multiplicative noise per series
    (lognormal sigma 0.27 vs 0.165 for non-perishables).
  - Intermittent demand: at item-store-day grain there are many real zeros.
  - Returns: a small fraction of negative unit_sales.
  - onpromotion with ~16% NaN (like the real file).

Usage:
    python generate_synthetic_favorita.py --scale mvp   # fast, for prototyping
    python generate_synthetic_favorita.py --scale full  # more stores/items/days

Output: CSVs in ./raw/ (train, stores, items, transactions, oil, holidays_events)
"""
from __future__ import annotations
import argparse
import os
import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)  # reproducible

# --- Realistic catalogs (subset of the real one, same names) ----------------
# Ecuadorian cities and provinces are real proper nouns from the Favorita
# dataset; kept in Spanish on purpose.
CITIES = [
    ("Quito", "Pichincha"), ("Guayaquil", "Guayas"), ("Cuenca", "Azuay"),
    ("Ambato", "Tungurahua"), ("Machala", "El Oro"), ("Manta", "Manabi"),
    ("Santo Domingo", "Santo Domingo de los Tsachilas"), ("Loja", "Loja"),
]
STORE_TYPES = ["A", "B", "C", "D", "E"]

# family -> (base mean, is_perishable, promo_lift, relative sales share)
FAMILIES = {
    "GROCERY I":     dict(base=9.0,  perishable=0, lift=1.6, share=0.30),
    "BEVERAGES":     dict(base=7.0,  perishable=0, lift=2.1, share=0.22),
    "PRODUCE":       dict(base=5.0,  perishable=1, lift=1.4, share=0.14),
    "CLEANING":      dict(base=4.0,  perishable=0, lift=1.8, share=0.10),
    "DAIRY":         dict(base=4.5,  perishable=1, lift=1.5, share=0.10),
    "BREAD/BAKERY":  dict(base=3.5,  perishable=1, lift=1.3, share=0.08),
    "DELI":          dict(base=2.5,  perishable=1, lift=1.4, share=0.03),
    "EGGS":          dict(base=3.0,  perishable=1, lift=1.5, share=0.03),
}


def make_stores(n_stores: int) -> pd.DataFrame:
    rows = []
    for s in range(1, n_stores + 1):
        city, state = CITIES[(s - 1) % len(CITIES)]
        rows.append(dict(
            store_nbr=s,
            city=city,
            state=state,
            type=STORE_TYPES[(s - 1) % len(STORE_TYPES)],
            cluster=int(1 + (s - 1) % 17),   # like the real one: clusters 1..17
        ))
    return pd.DataFrame(rows)


def make_items(n_items: int) -> pd.DataFrame:
    fams = list(FAMILIES.keys())
    # Distribute items across families by their 'share' (approx.)
    shares = np.array([FAMILIES[f]["share"] for f in fams])
    shares = shares / shares.sum()
    counts = np.maximum(1, (shares * n_items).astype(int))
    # Adjust to hit the exact total
    while counts.sum() < n_items:
        counts[RNG.integers(len(counts))] += 1
    while counts.sum() > n_items:
        idx = RNG.integers(len(counts))
        if counts[idx] > 1:
            counts[idx] -= 1

    rows, item_nbr = [], 100000
    for f, c in zip(fams, counts):
        for _ in range(c):
            item_nbr += 1
            rows.append(dict(
                item_nbr=item_nbr,
                family=f,
                # class: numeric code like the real one (groups items within family)
                class_=int(RNG.integers(1000, 9999)),
                perishable=FAMILIES[f]["perishable"],
            ))
    df = pd.DataFrame(rows).rename(columns={"class_": "class"})
    return df


def make_oil(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Synthetic WTI price: level ~40-55 with a random walk and some NaNs
    (like the real file, which has gaps on weekends/holidays)."""
    n = len(dates)
    steps = RNG.normal(0, 0.6, n).cumsum()
    price = 48 + steps * 0.3
    price = np.clip(price, 26, 62)
    # Introduce ~5% scattered NaNs (the real one has gaps)
    mask = RNG.random(n) < 0.05
    price[mask] = np.nan
    return pd.DataFrame({"date": dates, "dcoilwtico": np.round(price, 2)})


def make_holidays(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Ecuadorian national holidays (main fixed dates) + a few events. Column
    structure identical to the real one. Holiday descriptions are real Ecuadorian
    proper nouns; kept in Spanish on purpose."""
    fixed = {  # (month, day): description
        (1, 1): "Primer dia del ano", (5, 1): "Dia del Trabajo",
        (5, 24): "Batalla de Pichincha", (8, 10): "Primer Grito de Independencia",
        (10, 9): "Independencia de Guayaquil", (11, 2): "Dia de los Difuntos",
        (11, 3): "Independencia de Cuenca", (12, 25): "Navidad",
        (2, 27): "Carnaval", (2, 28): "Carnaval",
    }
    rows = []
    for d in dates:
        key = (d.month, d.day)
        if key in fixed:
            rows.append(dict(date=d, type="Holiday", locale="National",
                             locale_name="Ecuador", description=fixed[key],
                             transferred=False))
    # Special event: earthquake (in the real one it appears as an Event)
    quake = pd.Timestamp("2016-04-16")
    if quake in dates:
        rows.append(dict(date=quake, type="Event", locale="National",
                         locale_name="Ecuador", description="Terremoto Manabi",
                         transferred=False))
    return pd.DataFrame(rows)


def _weekly_factor(dow: int) -> float:
    # dow: 0=Monday ... 6=Sunday. Weekends higher.
    table = {0: 0.85, 1: 0.85, 2: 0.90, 3: 0.95, 4: 1.15, 5: 1.35, 6: 1.20}
    return table[dow]


def _payday_factor(day: int, last_day: int) -> float:
    # Spike around the 15th and month-end.
    if day in (14, 15, 16):
        return 1.20
    if day >= last_day - 1:
        return 1.15
    return 1.0


def _annual_factor(month: int) -> float:
    # December high, rest mild.
    table = {12: 1.30, 11: 1.05, 1: 0.95, 2: 0.90}
    return table.get(month, 1.0)


def make_train(stores: pd.DataFrame, items: pd.DataFrame,
               oil: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Generate item-store-day sales with all embedded signals. Only emits rows
    with sales > 0 (like the real one: no zero rows)."""
    oil_map = oil.set_index("date")["dcoilwtico"].ffill().bfill()
    oil_norm = (oil_map - oil_map.mean()) / oil_map.std()  # z-score for the macro effect

    quake = pd.Timestamp("2016-04-16")
    fam_meta = {r.item_nbr: FAMILIES[r.family] for r in items.itertuples()}
    perish_map = dict(zip(items.item_nbr, items.perishable))

    # Per-item popularity (some sell far more than others -> basis for ABC)
    item_pop = {it: RNG.lognormal(0, 0.7) for it in items.item_nbr}
    # Per-store popularity (large vs small stores)
    store_pop = {s: RNG.lognormal(0, 0.4) for s in stores.store_nbr}

    records = []
    n_days = len(dates)
    # Precompute calendar factors per date (independent of item/store)
    cal = []
    for d in dates:
        last_day = (d + pd.offsets.MonthEnd(0)).day
        cal.append((
            _weekly_factor(d.weekday()),
            _payday_factor(d.day, last_day),
            _annual_factor(d.month),
            float(oil_norm.get(d, 0.0)),
        ))

    for it in items.item_nbr:
        meta = fam_meta[it]
        base = meta["base"] * item_pop[it]
        lift = meta["lift"]
        is_perish = perish_map[it]
        # Perishables: more volatile (higher dispersion)
        disp = 0.9 if is_perish else 0.55
        # Probability the item sells that day in that store
        # (unpopular items -> many zeros -> real intermittency)
        sell_prob_base = min(0.9, 0.25 + 0.5 * min(item_pop[it], 2) / 2)

        for s in stores.store_nbr:
            sp = store_pop[s]
            for di in range(n_days):
                wf, pf, af, oilz = cal[di]
                d = dates[di]

                # promo: ~25% of item-days on promo, with 16% NaN applied later
                on_promo = RNG.random() < 0.25
                promo_mult = lift if on_promo else 1.0

                # macro oil effect (mild): +/- ~5%
                macro = 1.0 + 0.05 * oilz

                # earthquake shock: water/beverages/cleaning jump for ~2 weeks
                quake_mult = 1.0
                if meta_is_emergency(meta) and 0 <= (d - quake).days <= 14:
                    quake_mult = 2.4 - 0.1 * (d - quake).days  # decays

                lam = base * sp * wf * pf * af * macro * promo_mult * quake_mult

                # Does it sell today? (intermittency)
                if RNG.random() > sell_prob_base:
                    continue

                # Quantity: Poisson around lam, with over-dispersion for perishables
                noise = RNG.lognormal(0, disp * 0.3)
                qty = RNG.poisson(max(0.1, lam * noise))
                if qty <= 0:
                    continue

                # PRODUCE/DELI sometimes in kg -> float values (like the real one)
                if meta["perishable"] and RNG.random() < 0.15:
                    qty = round(qty * RNG.uniform(0.4, 1.6), 3)

                records.append((d, s, it, float(qty), on_promo))

    df = pd.DataFrame.from_records(
        records, columns=["date", "store_nbr", "item_nbr", "unit_sales", "onpromotion"]
    )

    # Returns: ~0.5% of rows become negative (like the real one)
    n_ret = int(len(df) * 0.005)
    if n_ret > 0:
        ret_idx = RNG.choice(df.index, n_ret, replace=False)
        df.loc[ret_idx, "unit_sales"] = -np.abs(
            RNG.integers(1, 4, n_ret)
        ).astype(float)

    # onpromotion: introduce ~16% NaN (like the real file)
    nan_mask = RNG.random(len(df)) < 0.16
    df["onpromotion"] = df["onpromotion"].astype("object")
    df.loc[nan_mask, "onpromotion"] = np.nan

    # unique id like the real one
    df = df.sort_values(["date", "store_nbr", "item_nbr"]).reset_index(drop=True)
    df.insert(0, "id", range(len(df)))
    return df


def meta_is_emergency(meta: dict) -> bool:
    """Families that react to the earthquake (water/beverages/cleaning)."""
    return meta["base"] in (7.0, 4.0) or meta["lift"] in (2.1, 1.8)


def make_transactions(train: pd.DataFrame) -> pd.DataFrame:
    """Transaction count per store-day (traffic proxy). Correlates with sales
    volume but is not identical."""
    daily = (train[train.unit_sales > 0]
             .groupby(["date", "store_nbr"])["unit_sales"].sum().reset_index())
    daily["transactions"] = np.maximum(
        1, (daily["unit_sales"] / RNG.uniform(3, 6) +
            RNG.normal(0, 20, len(daily))).astype(int)
    )
    return daily[["date", "store_nbr", "transactions"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", choices=["mvp", "full"], default="mvp")
    ap.add_argument("--outdir", default=os.path.join(os.path.dirname(__file__), "raw"))
    args = ap.parse_args()

    if args.scale == "mvp":
        n_stores, n_items = 6, 60
        start, end = "2015-01-01", "2016-08-15"
    else:
        n_stores, n_items = 12, 140
        start, end = "2014-01-01", "2016-08-15"

    dates = pd.date_range(start, end, freq="D")
    os.makedirs(args.outdir, exist_ok=True)

    print(f"[1/6] stores ({n_stores})...")
    stores = make_stores(n_stores)
    print(f"[2/6] items ({n_items})...")
    items = make_items(n_items)
    print(f"[3/6] oil ({len(dates)} days)...")
    oil = make_oil(dates)
    print(f"[4/6] holidays_events...")
    holidays = make_holidays(dates)
    print(f"[5/6] train (item x store x day with signals)... this takes a bit")
    train = make_train(stores, items, oil, dates)
    print(f"[6/6] transactions...")
    transactions = make_transactions(train)

    # Save (utf-8-sig for consistency)
    def save(df, name):
        path = os.path.join(args.outdir, f"{name}.csv")
        df.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"    -> {name}.csv  ({len(df):,} rows)")

    save(train, "train")
    save(stores, "stores")
    save(items, "items")
    save(transactions, "transactions")
    save(oil, "oil")
    save(holidays, "holidays_events")

    print("\nGenerated train summary:")
    pos = train[train.unit_sales > 0]
    print(f"  total rows          : {len(train):,}")
    print(f"  date range          : {train.date.min().date()} -> {train.date.max().date()}")
    print(f"  stores / items      : {train.store_nbr.nunique()} / {train.item_nbr.nunique()}")
    print(f"  negative sales      : {(train.unit_sales < 0).sum():,} (returns)")
    print(f"  onpromotion NaN     : {train.onpromotion.isna().sum():,} "
          f"({train.onpromotion.isna().mean():.1%})")
    print(f"  mean sales (>0)     : {pos.unit_sales.mean():.2f}")
    print("\nDone. CSVs in:", args.outdir)


if __name__ == "__main__":
    main()
