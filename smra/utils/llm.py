import os
import os
import re
import time
import logging

logger = logging.getLogger("smra.llm")

def call_llm(system_prompt: str, user_prompt: str) -> str:
    from groq import Groq
    
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    model = os.getenv("GROQ_MODEL", "mixtral-8x7b-32768")
    
    max_retries = 5
    wait_seconds = 3
    last_exc = None

    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt or "You are a helpful assistant."},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0,
                max_tokens=1000
            )
            return response.choices[0].message.content

        except Exception as e:
            last_exc = e
            err_str = str(e)
            logger.warning(f"LLM attempt {attempt} failed: {err_str[:120]}")

            # Parse wait time from Groq error message e.g. "try again in 2s"
            match = re.search(r'try again in (\d+(?:\.\d+)?)s', err_str)
            wait = float(match.group(1)) + 1 if match else wait_seconds

            if attempt < max_retries:
                logger.info(f"Waiting {wait}s before retry...")
                time.sleep(wait)

    raise RuntimeError(f"Groq failed after {max_retries} retries: {last_exc}")
