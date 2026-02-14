import duckdb

con = duckdb.connect("outputs/run_20260214_145600/model.duckdb")
print(con.execute("SELECT * FROM fact_enriched").fetchdf())