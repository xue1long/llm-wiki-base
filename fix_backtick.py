with open('web/app.js', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix literal backslash-backtick sequences that are invalid JS
# These came from Python script writing \` as \\`
fixes = [
    ('\\`\n', '`\n'),
    ('\\`;', '`;'),
    ("\\` +\n", '` +\n'),
]

for old, new in fixes:
    if old in content:
        content = content.replace(old, new)
        print(f'Fixed: {repr(old[:20])} -> {repr(new[:20])}')
    else:
        print(f'NOT FOUND: {repr(old[:30])}')

with open('web/app.js', 'w', encoding='utf-8') as f:
    f.write(content)
print('Done')
