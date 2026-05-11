import sqlite3
conn = sqlite3.connect(r'D:\translate-project\Minecraft-Translate-Proofread-Agent\data\Minecraft.db')
c = conn.cursor()

# Check changes=1 entries - how many versions per key?
c.execute('SELECT key, COUNT(*) as cnt FROM vanilla_keys WHERE changes=1 GROUP BY key ORDER BY cnt DESC LIMIT 20')
print('Changes=1 entries with most versions:')
for r in c.fetchall():
    print('  ' + r[0] + ': ' + str(r[1]) + ' versions')
print()

# Count how many unique keys have changes=1
c.execute('SELECT COUNT(DISTINCT key) FROM vanilla_keys WHERE changes=1')
print('Unique keys with changes=1:', c.fetchone()[0])

# Find a key with many changes
c.execute('SELECT key, COUNT(*) as cnt FROM vanilla_keys WHERE changes=1 GROUP BY key ORDER BY cnt DESC LIMIT 5')
keys = [r[0] for r in c.fetchall()]
for k in keys:
    c.execute('SELECT en_us, zh_cn, version_start, version_end FROM vanilla_keys WHERE key=? ORDER BY version_start', (k,))
    rows = c.fetchall()
    print(k + ' (' + str(len(rows)) + ' versions):')
    for r in rows:
        txt = r[1] + ' [version: ' + r[2] + '-' + r[3] + ']'
        print('    ' + r[0] + ' -> ' + txt)
