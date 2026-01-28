import polars as pl
from pathlib import Path

data_dir = Path("data")

tables={}
for csv_file in sorted(data_dir.glob("*.csv")):
    tables[csv_file.stem]=pl.read_csv(csv_file)

print("=== JOIN DISCOVERY ===")

table_names = list(tables.keys())

for i in range(len(table_names)):
    for j in range(i+1, len(table_names)):
        left_name = table_names[i]
        right_name = table_names[j]
        left = tables[left_name]
        right=tables[right_name]

        # Colonnes communes = jointure naturelle
        common_cols = set(left.columns).intersection(set(right.columns))
        if not common_cols:
            continue

        for key in sorted(common_cols):
            # On ne tente que si les types sont compatibles (ou castables)
            left_key = left.select(pl.col(key).cast(pl.Utf8)).to_series()
            right_key = right.select(pl.col(key).cast(pl.Utf8)).to_series()

            # Ignore si trop de nulls (clé pas fiable)
            if left_key.null_count() > 0 or right_key.null_count() > 0:
                continue

            # Coverage=% des valeurs de gauche présentes dans la droite
            right_set = set(right_key.to_list())
            left_list = left_key.to_list()

            matches = sum(1 for v in left_list if v in right_set)
            coverage = matches / len(left_list) * 100 if left_list else 0

            # Coverage + bonus si clé unique côté "dimension"
            right_unique = len(set(right_key.to_list())) == len(right_key)
            uniqueness_bonus = 10 if right_unique else 0
            score = coverage + uniqueness_bonus

            print(f"Candidate join: {left_name}.{key} ↔ {right_name}.{key}")
            print(f"  coverage(left->right): {coverage:.1f}% ({matches}/{len(left_list)})")
            print(f"  right_unique_key: {right_unique}")
            print(f"  score: {score:.1f}\n")