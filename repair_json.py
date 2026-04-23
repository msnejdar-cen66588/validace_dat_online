import json

def repair_and_parse(text: str) -> dict:
    if not text: return {}
    text = text.strip()
    if text.startswith("```json"): text = text[7:]
    elif text.startswith("```"): text = text[3:]
    if text.endswith("```"): text = text[:-3]
    text = text.strip()
    
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # Step 1: Fix obvious unescaped newlines inside strings 
        # (We iterate sequentially and track string states)
        in_string = False
        escaped = False
        result = []
        for char in text:
            if char == '"' and not escaped:
                in_string = not in_string
            if in_string and char == '\n':
                result.append('\\n')
            elif in_string and char == '\r':
                pass
            else:
                result.append(char)
            if char == '\\': escaped = not escaped
            else: escaped = False
            
        fixed_text = "".join(result)
        
        try:
            return json.loads(fixed_text)
        except json.JSONDecodeError:
            # Step 2: aggressive truncation recovery
            # If it failed, maybe it's cut off. Let's try to close strings and brackets.
            return force_close_json(fixed_text)

def force_close_json(text: str):
    # Try appending things until it parses
    # Extremely basic: track open braces and brackets
    in_str = False
    escaped = False
    braces = 0
    brackets = 0
    for char in text:
        if char == '"' and not escaped: in_str = not in_str
        elif not in_str:
            if char == '{': braces += 1
            elif char == '}': braces -= 1
            elif char == '[': brackets += 1
            elif char == ']': brackets -= 1
            
        if char == '\\': escaped = not escaped
        else: escaped = False

    append_str = ""
    if in_str:
        append_str += '"'
    
    # Simple strategy: just append the missing closures
    for _ in range(brackets): append_str += ']'
    for _ in range(braces): append_str += '}'
    
    try:
        return json.loads(text + append_str)
    except json.JSONDecodeError:
        try:
            # Maybe we need to close the string before adding brackets
            return json.loads(text + '"' + append_str.replace('"', ''))
        except json.JSONDecodeError:
            return {} # Give up and return empty dict safely

sample = '{\n  "metadata": "value",\n  "key": "Here is an unescaped \\n string'
print(repair_and_parse(sample))

sample2 = '{\n  "photos": [\n    {\n      "id": 1,\n      "description": "starts fine'
print(repair_and_parse(sample2))
