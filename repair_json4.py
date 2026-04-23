import json
import re

def force_close_json(text: str):
    # Strip whitespace to easily check trailing comma
    text = text.rstrip()
    if text.endswith(','):
        text = text[:-1]
        
    in_str = False
    escaped = False
    stack = []
    
    for char in text:
        if char == '"' and not escaped:
            in_str = not in_str
        elif not in_str:
            if char == '{': stack.append('}')
            elif char == '[': stack.append(']')
            elif char == '}' and stack and stack[-1] == '}': stack.pop()
            elif char == ']' and stack and stack[-1] == ']': stack.pop()
            
        if char == '\\': escaped = not escaped
        else: escaped = False

    append_str = ""
    if in_str:
        append_str += '"'
    
    while stack:
        append_str += stack.pop()
        
    try:
        return json.loads(text + append_str)
    except Exception as e:
        print(f"Still failed: {e}")
        return {}

sample3 = '{\n  "photos": [\n    {\n      "id": 1,\n      "description": "fine",\n'
print(force_close_json(sample3))
