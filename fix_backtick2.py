with open('web/app.js', 'rb') as f:
    data = f.read()

# Find all occurrences of backslash-backtick
import re
count = data.count(b'\\`')
print(f'Found {count} occurrences of backslash-backtick')

# Replace all backslash-backtick with just backtick
fixed = data.replace(b'\\`', b'`')

# Count again
count2 = fixed.count(b'\\`')
print(f'After fix: {count2} occurrences')

with open('web/app.js', 'wb') as f:
    f.write(fixed)
print('Done')
