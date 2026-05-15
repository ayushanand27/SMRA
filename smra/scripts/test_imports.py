import traceback

modules = [
    'smra.utils.llm',
    'smra.router',
    'smra.agents.sql_agent',
    'smra.agents.rag_agent',
    'smra.agents.web_agent'
]

for m in modules:
    try:
        __import__(m)
        print('imported', m)
    except Exception as e:
        print('FAILED', m, e)
        traceback.print_exc()
