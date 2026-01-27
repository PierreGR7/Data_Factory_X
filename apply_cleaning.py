import polars as pl

df = pl.read_csv("data.csv")

print("=== NETTOYAGE AVEC CONFIRMATION ===")

# On va faire simple : si une colonne est numérique et a des nulls -> proposer de remplir par la moyenne
clean_df = df.clone()

for col in df.columns:
    null_count = df[col].null_count()
    null_pct = null_count / df.height * 100
    if null_count == 0:
        continue

    dtype = df[col].dtype

    # On ne traite que les données numériques, donc int ou float
    if dtype in (pl.Int64, pl.Float64, pl.Int32, pl.Float32):
        mean_value = df[col].mean()

        print(f"Colonne '{col}' : {null_count} valeurs manquantes ({null_pct:.1f}% du total des lignes)")
        print(f"  - Suggestion : Remplacer les valeurs manquantes par la moyenne {mean_value}")

        answer = input(f"Appliquer ? (y/n): ").strip().lower()

        if answer == "y":
            clean_df = clean_df.with_columns(
                pl.col(col).fill_null(mean_value)
            )
            print("Modification appliquée.")

        else:
            print(f"Colonne '{col}' : {null_count} null(s), type={dtype}")
        

# Sauvegarde
clean_df.write_csv("clean_data.csv")
print("\nNettoyage terminé. Données sauvegardées dans clean_data.csv")

