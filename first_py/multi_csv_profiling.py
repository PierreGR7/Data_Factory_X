import polars as pl
from pathlib import Path

data_dir = Path("data")

print("=== PROFILING MULTIPLE CSV ===")

for csv_file in data_dir.glob("*.csv"):
    print(f"Fichier : {csv_file.name}")

    df = pl.read_csv(csv_file)

    print(f"  Lignes : {df.height}")
    print(f"  Colonnes : {df.width}")

    for col in df.columns:
        nulls = df[col].null_count()
        if nulls > 0:
            pct = nulls /df.height*100
            print(f" - {col} : {nulls} null(s) ({pct:.1f}%)")

    print()

