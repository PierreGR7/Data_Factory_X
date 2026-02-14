# Data Factory X — Run Report

## Tables

### customers
- rows: **3**, cols: **3**
- nulls:
  - `city`: 33.3%

### orders
- rows: **3**, cols: **3**
- nulls:
  - `amount`: 33.3%

## Top join candidates

- `customers.customer_id` ↔ `orders.customer_id` | cov L→R 66.67% | cov R→L 100.0% | unique L True / unique R False | score 93.33

## Star schema proposal

- FACT: **orders**
- Grain: **1 row per order_id**
- DIMENSIONS:
  - **customers** join on `orders.customer_id` → `customers.customer_id` (coverage ~100.0%)
