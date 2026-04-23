import json

def force_close_json(text: str):
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
    
    for _ in range(brackets): append_str += ']'
    for _ in range(braces): append_str += '}'
    
    print(f"Trying to parse: {text + append_str}")
    try:
        return json.loads(text + append_str)
    except Exception as e:
        print(e)
        return {}

sample2 = '{\n  "photos": [\n    {\n      "id": 1,\n      "description": "starts fine'
print(force_close_json(sample2))
