"""Deterministic synthetic e-commerce database for execution-based SQL scoring.

The `code` use case is scored by running the model's SQL and a reference SQL on this database
and comparing result sets. Same seed -> same data on every machine.
"""
from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timedelta

SCHEMA_DOC = """Tables (SQLite):
orders(order_id INTEGER PRIMARY KEY, customer_id INTEGER, city TEXT, pincode TEXT,
       created_at TEXT -- 'YYYY-MM-DD HH:MM:SS', status TEXT -- one of DELIVERED, RTO, CANCELLED, IN_TRANSIT,
       payment_mode TEXT -- one of COD, UPI, CARD, amount_inr REAL)
returns(return_id INTEGER PRIMARY KEY, order_id INTEGER, created_at TEXT -- 'YYYY-MM-DD HH:MM:SS',
        reason TEXT -- one of DAMAGED, WRONG_ITEM, SIZE_ISSUE, NOT_NEEDED, refund_inr REAL)"""

CITIES = {
    "Mumbai": ["400001", "400053", "400069", "400076"],
    "Delhi": ["110001", "110017", "110024", "110085"],
    "Bengaluru": ["560001", "560034", "560066", "560100"],
    "Chennai": ["600001", "600017", "600040"],
    "Hyderabad": ["500001", "500032", "500081"],
    "Lucknow": ["226001", "226010"],
    "Patna": ["800001", "800020"],
    "Guwahati": ["781001", "781005"],
}


def build_db(seed: int = 7, n_orders: int = 6000, n_customers: int = 300) -> sqlite3.Connection:
    rng = random.Random(seed)
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE orders(order_id INTEGER PRIMARY KEY, customer_id INTEGER, city TEXT, pincode TEXT,"
                " created_at TEXT, status TEXT, payment_mode TEXT, amount_inr REAL)")
    con.execute("CREATE TABLE returns(return_id INTEGER PRIMARY KEY, order_id INTEGER, created_at TEXT,"
                " reason TEXT, refund_inr REAL)")
    start = datetime(2026, 9, 1)
    pins = [(c, p) for c, ps in CITIES.items() for p in ps]
    rid = 1
    for oid in range(1, n_orders + 1):
        city, pin = rng.choice(pins)
        created = start + timedelta(seconds=rng.randrange(0, 91 * 24 * 3600))   # Sep–Nov 2026
        pay = rng.choices(["COD", "UPI", "CARD"], [0.4, 0.45, 0.15])[0]
        # RTO is likelier for COD and for some smaller cities, so the RTO question has a real answer.
        rto_p = (0.18 if pay == "COD" else 0.05) + (0.08 if city in ("Patna", "Guwahati", "Lucknow") else 0)
        status = rng.choices(["DELIVERED", "RTO", "CANCELLED", "IN_TRANSIT"],
                             [1 - rto_p - 0.07, rto_p, 0.05, 0.02])[0]
        amount = round(rng.choice([199, 349, 499, 799, 999, 1299, 1799, 2499, 3999]) * rng.uniform(0.8, 1.0), 2)
        con.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)",
                    (oid, rng.randint(1, n_customers), city, pin, created.strftime("%Y-%m-%d %H:%M:%S"),
                     status, pay, amount))
        if status == "DELIVERED" and rng.random() < 0.12:
            reason = rng.choices(["DAMAGED", "WRONG_ITEM", "SIZE_ISSUE", "NOT_NEEDED"], [0.2, 0.15, 0.45, 0.2])[0]
            ret_at = created + timedelta(days=rng.randint(2, 4) + {"DAMAGED": 0, "WRONG_ITEM": 1,
                                                                   "SIZE_ISSUE": 3, "NOT_NEEDED": 5}[reason],
                                         hours=rng.randint(0, 23))
            con.execute("INSERT INTO returns VALUES (?,?,?,?,?)",
                        (rid, oid, ret_at.strftime("%Y-%m-%d %H:%M:%S"), reason, amount))
            rid += 1
    con.commit()
    return con


TOL = 0.006   # numeric tolerance: reference rounds to 2-3 dp, a correct candidate may not round at all


def _eq(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= max(TOL, abs(b) * 1e-6)   # absolute for rates, relative for big GMV sums
    return str(a).strip() == str(b).strip()


def _key(v):
    return (0, float(v), "") if isinstance(v, (int, float)) else (1, 0.0, str(v).strip())


def _col_eq(x: list, y: list) -> bool:
    return len(x) == len(y) and all(_eq(a, b) for a, b in zip(sorted(x, key=_key), sorted(y, key=_key)))


def results_match(con: sqlite3.Connection, candidate_sql: str, reference_sql: str) -> tuple[bool, str]:
    """Run both queries; pass if every reference column is matched by some candidate column and rows agree.

    Lenient on column names, column order, rounding (TOL) and extra columns; strict on the row set.
    """
    try:
        ref = con.execute(reference_sql).fetchall()
    except sqlite3.Error as e:
        raise RuntimeError(f"reference SQL broken: {e}")
    try:
        cand = con.execute(candidate_sql).fetchall()
    except sqlite3.Error as e:
        return False, f"sql_error: {e}"
    if len(cand) != len(ref):
        return False, f"row_count {len(cand)} vs {len(ref)}"
    if not ref:
        return True, "both empty"
    ref_cols, cand_cols = list(zip(*ref)), list(zip(*cand))
    mapping, used = [], set()
    for rc in ref_cols:
        j = next((j for j, cc in enumerate(cand_cols) if j not in used and _col_eq(list(cc), list(rc))), None)
        if j is None:
            return False, "column values differ"
        mapping.append(j)
        used.add(j)
    proj = sorted((tuple(r[j] for j in mapping) for r in cand), key=lambda t: tuple(map(_key, t)))
    refs = sorted((tuple(r) for r in ref), key=lambda t: tuple(map(_key, t)))
    if all(all(_eq(a, b) for a, b in zip(x, y)) for x, y in zip(proj, refs)):
        return True, "match"
    return False, "rows differ"
