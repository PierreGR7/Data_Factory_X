import polars as pl
from pathlib import Path

data_dir = Path("data")

# On commence par charger les tables
tables={}
for csv_file in data_dir.glob("*.csv"):
    tables[csv_file.stem]=pl.read_csv(csv_file)

# Résultats connus (issus de find_joins.py, on écrit en dur pour l'instant)
fact_table = "orders"
dimension_tables = ["customers"]
join_key = "customer_id"

print("=== PROPOSITION DE MODELE DIMENSIONNEL ===\n")

# 1. Fact
fact_df = tables[fact_table]
print(f"FACT TABLE : {fact_table}")
print(f"  - Nombre de lignes : {fact_df.height}")
print(f"  - Colonnes : {fact_df.columns}")

# Estimation du grain (clé primaire supposée)
if "order_id" in fact_df.columns:
    grain = "1 ligne = 1 order (order_id)"
else:
    grain = "grain inconnu (clé primair enon détectée)"

print(f" Grain estimé : {grain}\n")

# 2. dim
for dim in dimension_tables:
    dim_df = tables[dim]
    print(f"DIMENSION TABLE : {dim}")
    print(f"  - Nombre de lignes : {dim_df.height}")
    print(f"  - Colonnes descriptives : {dim_df.columns}")
    print(f"  - Clé de jointure : {join_key}\n")

# 3. Jointure
print("JOINTURE PROPOSEE :")
print(f"{fact_table}.{join_key} → {dimension_tables[0]}.{join_key}")
print("Type : many-to-one (FACT → DIMENSION)\n")