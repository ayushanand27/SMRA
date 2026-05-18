import os, pickle
from dotenv import load_dotenv

load_dotenv()

p = os.path.join(os.path.dirname(__file__), '..', 'data', 'rag_local_store.pkl')
p = os.path.normpath(p)
print('Checking file:', p)
if not os.path.exists(p):
    print('NOT FOUND')
    raise SystemExit(1)

with open(p, 'rb') as f:
    store = pickle.load(f)

print('Store type:', type(store))
if isinstance(store, dict):
    for k, v in store.items():
        try:
            l = len(v)
        except Exception:
            l = 'n/a'
        print(f"- {k}: type={type(v)}, len={l}")
    if 'texts' in store and store['texts']:
        print('First text sample (first 200 chars):')
        print(store['texts'][0][:200].replace('\n',' '))
    if 'vectors' in store and store['vectors']:
        try:
            print('First vector length:', len(store['vectors'][0]))
        except Exception as e:
            print('Could not read vector length:', e)
else:
    print('Store is not a dict; raw repr:')
    print(repr(store))
