import polars as pl

# Read data
df = pl.read_csv("data.csv")

print("=== PROFILING ===")
print(f"Nombre de lignes : {df.height}")
print(f"Nombre de colonnes : {df.width}\n")

for col in df.columns:
    null_count = df[col].null_count()
    null_pct = null_count / df.height * 100

    print(f"Colonne : {col}")
    print(f"  - Type : {df[col].dtype}")
    print(f"  - Valeurs manquantes : {null_count} ({null_pct:.1f}%)\n")