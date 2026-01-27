import polars as pl

df = pl.read_csv("data.csv")

print("DATA")
print(df)

print("\nNombre de lignes :", df.height)
print("\nColonnes :", df.columns)