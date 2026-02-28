import codecs

with codecs.open('app.py', 'r', 'utf-8') as f:
    lines = f.readlines()

for i in range(1501, 1682):
    lines[i] = "    " + lines[i]

with codecs.open('app.py', 'w', 'utf-8') as f:
    f.writelines(lines)

print("Indentation fixed.")
