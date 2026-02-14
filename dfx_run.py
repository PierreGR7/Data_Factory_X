from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import polars as pl
import duckdb


DATA_DIR = Path("data")
OUT_ROOT = Path("outputs")

MEASURE_KEYWORDS = ["amount", "price", "qty", "quantity", "total", "revenue", "sales"]
TEXT_KEYWORDS = ["name", "city", "country", "category", "type", "desc", "description"]
ID_HINTS = ["_id", "id"]


@dataclass
class TableProfile:
    name: str
    rows: int
    cols: int
    dtypes: Dict[str, str]
    null_pct: Dict[str, float]
    unique_pct: Dict[str, float]


def now_run_dir() -> Path:
    '''
    Create a timestamped run directory inside outputs/.
    Each execution of the pipeline writes its artifacts there.
    '''
    run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    run_dir = OUT_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def load_tables(data_dir: Path) -> Dict[str, pl.DataFrame]:
    '''
    Load all CSV files from the data directory into a dictionary
    where keys are table names and values are Polars DataFrames.
    '''
    tables: Dict[str, pl.DataFrame] = {}
    for p in sorted(data_dir.glob("*.csv")):
        tables[p.stem] = pl.read_csv(p, try_parse_dates=True)
    if not tables:
        raise SystemExit("No CSV files found in data/ directory.")
    return tables


def profile_table(name: str, df: pl.DataFrame) -> TableProfile:
    '''
    Compute basic profiling metrics for a table:
    - row and column counts
    - data types
    - null percentages
    - uniqueness ratios
    '''
    rows = df.height
    dtypes = {c: str(df[c].dtype) for c in df.columns}

    null_pct = {}
    unique_pct = {}
    for c in df.columns:
        nc = df[c].null_count()
        null_pct[c] = (nc / rows * 100) if rows else 0.0

        try:
            uniq = df[c].n_unique()
            unique_pct[c] = (uniq / rows * 100) if rows else 0.0
        except Exception:
            unique_pct[c] = 0.0

    return TableProfile(
        name=name,
        rows=rows,
        cols=df.width,
        dtypes=dtypes,
        null_pct=null_pct,
        unique_pct=unique_pct,
    )


def guess_fact_dim(df: pl.DataFrame) -> Tuple[int, int]:
    '''
    Score a table as FACT or DIMENSION using simple heuristics:
    - measure-like columns increase fact score
    - text columns increase dimension score
    - descriptive keywords increase dimension score
    - date columns increase fact score
    '''
    fact_score = 0
    dim_score = 0

    cols_lower = [c.lower() for c in df.columns]

    for c in cols_lower:
        if any(k in c for k in MEASURE_KEYWORDS):
            fact_score += 3

    for c in df.columns:
        if df[c].dtype == pl.Utf8:
            dim_score += 1

    for c in cols_lower:
        if any(k in c for k in TEXT_KEYWORDS):
            dim_score += 2

    for c in df.columns:
        if df[c].dtype in (pl.Date, pl.Datetime):
            fact_score += 2

    return fact_score, dim_score


def candidate_keys(profile: TableProfile) -> List[str]:
    '''
    Detect candidate primary keys based on:
    - no nulls
    - high uniqueness ratio
    - column name resembling an ID
    '''
    keys = []
    for c in profile.dtypes:
        if profile.null_pct.get(c, 100) > 0:
            continue
        if profile.unique_pct.get(c, 0) < 60:
            continue
        cl = c.lower()
        if any(h in cl for h in ID_HINTS):
            keys.append(c)
    return keys


def join_discovery(tables: Dict[str, pl.DataFrame], profiles: Dict[str, TableProfile]):
    '''
    Discover possible joins between tables by:
    - finding common column names
    - computing bidirectional coverage
    - checking uniqueness
    - assigning a simple join quality score
    '''
    joins = []
    names = list(tables.keys())

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            df_a, df_b = tables[a], tables[b]

            common = sorted(set(df_a.columns).intersection(set(df_b.columns)))
            if not common:
                continue

            for key in common:
                if df_a[key].null_count() > 0 or df_b[key].null_count() > 0:
                    continue

                a_vals = df_a.select(pl.col(key).cast(pl.Utf8)).to_series().to_list()
                b_vals = df_b.select(pl.col(key).cast(pl.Utf8)).to_series().to_list()

                if not a_vals or not b_vals:
                    continue

                set_b = set(b_vals)
                set_a = set(a_vals)

                cov_a_to_b = sum(1 for v in a_vals if v in set_b) / len(a_vals) * 100
                cov_b_to_a = sum(1 for v in b_vals if v in set_a) / len(b_vals) * 100

                b_unique = len(set_b) == len(b_vals)
                a_unique = len(set_a) == len(a_vals)

                score = (cov_a_to_b + cov_b_to_a) / 2 + (10 if a_unique or b_unique else 0)

                joins.append(
                    {
                        "left": a,
                        "right": b,
                        "key": key,
                        "coverage_left_to_right": round(cov_a_to_b, 2),
                        "coverage_right_to_left": round(cov_b_to_a, 2),
                        "left_unique": a_unique,
                        "right_unique": b_unique,
                        "score": round(score, 2),
                    }
                )

    joins.sort(key=lambda x: x["score"], reverse=True)
    return joins


def choose_star_schema(
    tables: Dict[str, pl.DataFrame],
    profiles: Dict[str, TableProfile],
    joins: List[dict],
):
    '''
    Select the most likely star schema:
    - choose the best FACT table
    - attach dimension tables based on join quality
    - estimate the grain of the fact table
    '''
    scored = []
    for name, df in tables.items():
        f, d = guess_fact_dim(df)
        scored.append((name, f, d, f - d, df.height))
    scored.sort(key=lambda x: (x[3], x[4]), reverse=True)

    fact = scored[0][0]
    dims = []

    for j in joins:
        if j["left"] == fact or j["right"] == fact:
            other = j["right"] if j["left"] == fact else j["left"]
            if other in dims:
                continue
            cov = j["coverage_left_to_right"] if j["left"] == fact else j["coverage_right_to_left"]
            other_unique = j["right_unique"] if j["right"] == other else j["left_unique"]
            if cov >= 60 and other_unique:
                dims.append((other, j["key"], cov))
            if len(dims) >= 5:
                break

    prof_fact = profiles[fact]
    grain = "unknown"
    for c in prof_fact.dtypes:
        if c.lower().endswith("_id"):
            if prof_fact.null_pct.get(c, 100) == 0 and prof_fact.unique_pct.get(c, 0) >= 60:
                grain = f"1 row per {c}"
                break

    return {
        "fact_table": fact,
        "dimensions": [{"table": t, "key": k, "coverage": cov} for (t, k, cov) in dims],
        "grain": grain,
    }


def build_duckdb_model(run_dir: Path, tables: Dict[str, pl.DataFrame], schema: dict):
    '''
    Build a physical star-schema-style table in DuckDB:
    - load all tables into DuckDB
    - join fact with dimensions
    - create a materialized table called fact_enriched
    '''
    db_path = run_dir / "model.duckdb"
    con = duckdb.connect(str(db_path))

    # Register tables in DuckDB
    for name, df in tables.items():
        con.register(name, df.to_pandas())

    fact = schema["fact_table"]
    dims = schema["dimensions"]

    select_clause = f"SELECT {fact}.*"
    join_clauses = ""

    for dim in dims:
        dname = dim["table"]
        key = dim["key"]
        alias = f"d_{dname}"
        select_clause += f", {alias}.*"
        join_clauses += f"\nLEFT JOIN {dname} {alias} ON {fact}.{key} = {alias}.{key}"

    sql = f"""
    CREATE OR REPLACE TABLE fact_enriched AS
    {select_clause}
    FROM {fact}
    {join_clauses};
    """

    con.execute(sql)
    con.close()

    return db_path


def main():
    run_dir = now_run_dir()
    tables = load_tables(DATA_DIR)

    profiles = {name: profile_table(name, df) for name, df in tables.items()}
    joins = join_discovery(tables, profiles)
    schema = choose_star_schema(tables, profiles, joins)

    # Build DuckDB model
    db_path = build_duckdb_model(run_dir, tables, schema)

    summary = {
        "joins": joins,
        "star_schema": schema,
        "duckdb_model": str(db_path),
    }

    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Run completed: {run_dir}")
    print(f"DuckDB model: {db_path}")


if __name__ == "__main__":
    main()