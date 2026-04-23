import json

sample2 = '{\n  "metadata": "value",\n  "key": "Here is an unescaped \\" quote inside string"\n}'
try:
    json.loads(sample2)
except Exception as e:
    print(f"Sample 2: {e}")

sample3 = '{\n  "key": "Starts but does not'
try:
    json.loads(sample3)
except Exception as e:
    print(f"Sample 3: {e}")

