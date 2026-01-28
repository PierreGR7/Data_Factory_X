import csv
import polars as pl
from pathlib import Path

data_dir = Path("data")

MEASURE_KEYWORDS = ["amount", "price", "qty", "quantity","total","revenue","sales"]
TEXT_KEYWORDS = ["name", "city", "country", "category", "type", "desc", "description"]

def score_table(df : pl.DataFrame, table_name: str):
    fact_score = 0
    dim_score = 0

    cols = [c.lower() for c in df.columns]

    # mots clés mesure => plutôt fact
    for c in cols:
        if any(k in c for k in MEASURE_KEYWORDS):
            fact_score += 3

    # colonnes textes => plutôt dim
    for c in cols:
        if df[c].dtype == pl.Utf8:
            dim_score += 1

    # mots clés descriptifs => plutôt dim
    for c in cols:
        if any(k in c for k in TEXT_KEYWORDS):
            dim_score += 3

    if fact_score>dim_score:
        kind ="FACT"
    elif dim_score>fact_score:
        kind ="DIMENSION"
    else:
        kind="UNDEFINED"

    return{
        "table":table_name,
        "rows":df.height,
        "cols":df.width,
        "fact_score":fact_score,
        "dim_score":dim_score,
        "guess":kind
    }

print("=== FACT vs DIMENSION ===\n")

results=[]

for csv_file in sorted(data_dir.glob("*.csv")):
    df = pl.read_csv(csv_file)
    res = score_table(df, csv_file.stem)
    results.append(res)

for r in results:
    print(f"Table: {r['table']}")
    print(f"  rows={r['rows']} cols={r['cols']}")
    print(f"  fact_score={r['fact_score']} dim_score={r['dim_score']}")
    print(f"  => GUESS: {r['guess']}\n")