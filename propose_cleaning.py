import polars as pl

df = pl.read_csv("data.csv")

print("=== PROPOSITION DE NETTOYAGE ===")

for col in df.columns:
    null_count = df[col].null_count()
    null_pct = null_count / df.height * 100

    # Cas 1 : valeurs manquantes
    if null_pct > 0:
        if null_pct < 10 :
            print(f"Colonne '{col}' : {null_count} valeurs manquantes faibles ({null_pct:.1f}% du total des lignes)")
            print("  - Suggestion : Supprimer les lignes avec les valeurs manquantes")

        elif null_pct < 40:
            print(f"Colonne '{col}' : {null_count} valeurs manquantes modérées ({null_pct:.1f}% du total des lignes)")
            print("  - Suggestion : Remplacer les valeurs manquantes par la moyenne de la colonne")

        else:
            print(f"Colonne '{col}' : {null_count} valeurs manquantes élevées ({null_pct:.1f}% du total des lignes)")
            print("  - Suggestion : Envisager de supprimer la colonne")