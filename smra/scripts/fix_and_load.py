#!/usr/bin/env python3
"""Backup/remove placeholder DB, run loader, and verify tables."""
import shutil
import os
import subprocess
import sys
import sqlite3
import traceback

base_db = os.path.join('smra', 'data', 'smra.db')
bak = base_db + '.bak'

try:
    if os.path.exists(base_db):
        shutil.copy2(base_db, bak)
        print(f'Backed up {base_db} -> {bak}')
        os.remove(base_db)
        print(f'Removed placeholder {base_db}')
    else:
        print(f'No existing {base_db} found, proceeding.')
except Exception as e:
    print('Backup/remove failed:', e)
    traceback.print_exc()
    sys.exit(1)

# Run loader
cmd = [sys.executable, os.path.join('smra', 'data', 'load_db.py'), '--excel', os.path.join('smra', 'data', 'stock_market_data.xlsx'), '--db', base_db, '--set-columns']
print('Running loader:', ' '.join(cmd))

p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
print('Loader output:\n')
print(p.stdout)
if p.returncode != 0:
    print('Loader failed with exit code', p.returncode)
    sys.exit(p.returncode)

# Verify tables
try:
    conn = sqlite3.connect(base_db)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    rows = cur.fetchall()
    print('Tables found:', rows)
    conn.close()
except Exception as e:
    print('Verification failed:', e)
    traceback.print_exc()
    sys.exit(1)

print('Done')
