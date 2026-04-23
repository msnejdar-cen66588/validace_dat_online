import json

def robust_json_parse(text: str) -> dict:
    if not text: return {}
    text = text.strip()
    if text.startswith("```json"): text = text[7:]
    elif text.startswith("```"): text = text[3:]
    if text.endswith("```"): text = text[:-3]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"Failed standard: {e}")
        # Try to fix unescaped newlines inside strings
        in_string = False
        escaped = False
        result = []
        for char in text:
            if char == '"' and not escaped:
                in_string = not in_string
            if in_string and char == '\n':
                result.append('\\n') # <----- THIS IS WHAT WAS MISSING: returning actual \n instead of space, or just space is fine.
            elif in_string and char == '\r':
                pass
            else:
                result.append(char)
            if char == '\\': escaped = not escaped
            else: escaped = False
        fixed_text = "".join(result)
        try:
            return json.loads(fixed_text)
        except json.JSONDecodeError as e2:
            print(f"Failed fixed: {e2}")
            import re
            fixed_2 = re.sub(r'\\([^"\\/bfnrtu])', r'\1', fixed_text)
            try:
                return json.loads(fixed_2)
            except Exception as e3:
                raise e3

sample = """
{
  "test": "line 1
line 2"
}
"""
print(robust_json_parse(sample))
