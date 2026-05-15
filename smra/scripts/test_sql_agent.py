import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure we can import the project modules
script_dir = Path(__file__).resolve().parent
smra_root = script_dir.parent
# Load .env explicitly from smra root
env_path = smra_root / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)
else:
    load_dotenv(override=True)

# Add smra root to sys.path so both `agents` and `smra.agents` imports work
sys.path.insert(0, str(smra_root))

# Try importing the SQL agent from either import style
try:
    from agents.sql_agent import run_sql_agent
except Exception:
    from smra.agents.sql_agent import run_sql_agent

q = "What was AAPL closing price on 2025-01-02?"
print(f"Running SQL agent query: {q}\n")

try:
    r = run_sql_agent(q)
except Exception as e:
    print("ERROR while running run_sql_agent:")
    raise

print('\nRESULT')
print('ANSWER:', r.get('answer'))
print('SQL:', r.get('sql'))

# Safely inspect the returned data which may be a pandas DataFrame or a list
data = r.get('data')
rows_count = 0
try:
    # If it's a pandas DataFrame
    import pandas as _pd
    if data is None:
        rows_count = 0
    elif hasattr(data, 'empty'):
        rows_count = 0 if data.empty else len(data)
    else:
        rows_count = len(data)
except Exception:
    try:
        rows_count = len(data) if data is not None else 0
    except Exception:
        rows_count = 0

print('ROWS:', rows_count)

if data is not None:
    try:
        import pandas as _pd
        if hasattr(data, 'empty'):
            if not data.empty:
                print('SAMPLE ROW 0:', data.iloc[0].to_dict())
        elif isinstance(data, (list, tuple)):
            if len(data) > 0:
                print('SAMPLE ROW 0:', data[0])
        else:
            print('SAMPLE ROW 0:', data)
    except Exception:
        print('SAMPLE ROW 0:', data)
