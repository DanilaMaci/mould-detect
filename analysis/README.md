# Analysis (Python)

Planned layout; folders are created with their first code.

| Path | Contents |
|---|---|
| `src/mould/` | Package: psychrometrics (dew point, absolute humidity, surface RH), wall temperature factor, mould index, features, forecasting |
| `tests/` | pytest tests; physics checked against hand-calculated reference values |
| `notebooks/` | Exploration and model experiments. Clear outputs before committing: they can contain real data |
| `samples/` | Small synthetic CSV examples, safe to publish |

Real exports from Supabase go in the repository-level `data/` folder, which is never committed.
