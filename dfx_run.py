from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import polars as pl


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
    run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    run_dir = OUT_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def load_tables(data_dir: Path) -> Dict[str, pl.DataFrame]:
    tables: Dict[str, pl.DataFrame] = {}
    for p in sorted(data_dir.glob("*.csv")):
        tables[p.stem] = pl.read_csv(p, try_parse_dates=True)
    if not tables:
        raise SystemExit("Aucun CSV trouvé dans data/. Mets tes fichiers .csv dedans puis relance.")
    return tables


def profile_table(name: str, df: pl.DataFrame) -> TableProfile:
    rows = df.height
    dtypes = {c: str(df[c].dtype) for c in df.columns}

    null_pct = {}
    unique_pct = {}
    for c in df.columns:
        nc = df[c].null_count()
        null_pct[c] = (nc / rows * 100) if rows else 0.0

        # unique ratio (simple; ok pour MVP)
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
    fact_score = 0
    dim_score = 0

    cols_lower = [c.lower() for c in df.columns]

    # measures => fact
    for c in cols_lower:
        if any(k in c for k in MEASURE_KEYWORDS):
            fact_score += 3

    # text cols => dim
    for c in df.columns:
        if df[c].dtype == pl.Utf8:
            dim_score += 1

    # descriptive keywords => dim
    for c in cols_lower:
        if any(k in c for k in TEXT_KEYWORDS):
            dim_score += 2

    # dates => fact (si polars parse des dates)
    for c in df.columns:
        if df[c].dtype in (pl.Date, pl.Datetime):
            fact_score += 2

    return fact_score, dim_score


def candidate_keys(profile: TableProfile) -> List[str]:
    # clés candidates = peu/pas de null + unique élevé + nom qui ressemble à un id
    keys = []
    for c in profile.dtypes:
        if profile.null_pct.get(c, 100) > 0:
            continue
        if profile.unique_pct.get(c, 0) < 60:  # seuil simple pour petits datasets
            continue
        cl = c.lower()
        if any(h in cl for h in ID_HINTS):
            keys.append(c)
    return keys


def join_discovery(tables: Dict[str, pl.DataFrame], profiles: Dict[str, TableProfile]):
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
                # skip if any nulls (simple rule)
                if df_a[key].null_count() > 0 or df_b[key].null_count() > 0:
                    continue

                # cast to string to avoid type mismatch headaches
                a_vals = df_a.select(pl.col(key).cast(pl.Utf8)).to_series().to_list()
                b_vals = df_b.select(pl.col(key).cast(pl.Utf8)).to_series().to_list()

                if not a_vals or not b_vals:
                    continue

                set_b = set(b_vals)
                set_a = set(a_vals)

                # coverage in both directions
                cov_a_to_b = sum(1 for v in a_vals if v in set_b) / len(a_vals) * 100
                cov_b_to_a = sum(1 for v in b_vals if v in set_a) / len(b_vals) * 100

                # uniqueness
                b_unique = len(set_b) == len(b_vals)
                a_unique = len(set_a) == len(a_vals)

                # simple score (favor coverage + dim uniqueness)
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
    # pick fact = table with highest (fact_score - dim_score), tie-breaker by rows
    scored = []
    for name, df in tables.items():
        f, d = guess_fact_dim(df)
        scored.append((name, f, d, f - d, df.height))
    scored.sort(key=lambda x: (x[3], x[4]), reverse=True)

    fact = scored[0][0]
    dims = []

    # pick top joins that involve the fact and look like many-to-one (dim unique)
    for j in joins:
        if j["left"] == fact or j["right"] == fact:
            other = j["right"] if j["left"] == fact else j["left"]
            # require decent coverage + uniqueness on the dimension side
            if other in dims:
                continue
            cov = j["coverage_left_to_right"] if j["left"] == fact else j["coverage_right_to_left"]
            other_unique = j["right_unique"] if j["right"] == other else j["left_unique"]
            if cov >= 60 and other_unique:
                dims.append((other, j["key"], cov))
            if len(dims) >= 5:
                break

    # grain guess: if order_id-like exists and mostly unique
    prof_fact = profiles[fact]
    grain = "unknown"
    for c in prof_fact.dtypes:
        if c.lower() in ["order_id", "transaction_id", "event_id"] or c.lower().endswith("_id"):
            if prof_fact.null_pct.get(c, 100) == 0 and prof_fact.unique_pct.get(c, 0) >= 60:
                grain = f"1 row per {c}"
                break

    return {
        "fact_table": fact,
        "dimensions": [{"table": t, "key": k, "coverage": cov} for (t, k, cov) in dims],
        "grain": grain,
        "fact_dim_scores": [
            {"table": name, "fact_score": f, "dim_score": d, "delta": delta, "rows": rows}
            for (name, f, d, delta, rows) in scored
        ],
    }


def make_report_md(profiles: Dict[str, TableProfile], joins: List[dict], schema: dict) -> str:
    lines = []
    lines.append("# Data Factory X — Run Report\n")

    lines.append("## Tables\n")
    for name, p in profiles.items():
        lines.append(f"### {name}")
        lines.append(f"- rows: **{p.rows}**, cols: **{p.cols}**")
        # show nulls
        bad_nulls = [(c, v) for c, v in p.null_pct.items() if v > 0]
        if bad_nulls:
            lines.append("- nulls:")
            for c, v in sorted(bad_nulls, key=lambda x: x[1], reverse=True):
                lines.append(f"  - `{c}`: {v:.1f}%")
        else:
            lines.append("- nulls: none")
        lines.append("")

    lines.append("## Top join candidates\n")
    if joins:
        for j in joins[:5]:
            lines.append(
                f"- `{j['left']}.{j['key']}` ↔ `{j['right']}.{j['key']}` | "
                f"cov L→R {j['coverage_left_to_right']}% | cov R→L {j['coverage_right_to_left']}% | "
                f"unique L {j['left_unique']} / unique R {j['right_unique']} | score {j['score']}"
            )
    else:
        lines.append("- No joins detected.")
    lines.append("")

    lines.append("## Star schema proposal\n")
    lines.append(f"- FACT: **{schema['fact_table']}**")
    lines.append(f"- Grain: **{schema['grain']}**")
    if schema["dimensions"]:
        lines.append("- DIMENSIONS:")
        for d in schema["dimensions"]:
            lines.append(
                f"  - **{d['table']}** join on `{schema['fact_table']}.{d['key']}` → `{d['table']}.{d['key']}` "
                f"(coverage ~{d['coverage']:.1f}%)"
            )
    else:
        lines.append("- DIMENSIONS: none confidently detected (coverage/unique too weak).")
    lines.append("")

    return "\n".join(lines)


def main():
    run_dir = now_run_dir()
    tables = load_tables(DATA_DIR)

    profiles = {name: profile_table(name, df) for name, df in tables.items()}
    joins = join_discovery(tables, profiles)
    schema = choose_star_schema(tables, profiles, joins)

    # Write outputs
    out_profiles = {k: profiles[k].__dict__ for k in profiles}
    summary = {
        "tables": out_profiles,
        "joins": joins,
        "star_schema": schema,
    }

    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(make_report_md(profiles, joins, schema), encoding="utf-8")

    print(f"✅ Run completed: {run_dir}")
    print(f"- summary: {run_dir / 'summary.json'}")
    print(f"- report : {run_dir / 'report.md'}")


if __name__ == "__main__":
    main()