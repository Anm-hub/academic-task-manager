import sqlite3

conn = sqlite3.connect("database.db")
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE user ADD COLUMN otp_code TEXT")
    cursor.execute("ALTER TABLE user ADD COLUMN otp_expiry DATETIME")
    print("✅ Columns added successfully")
except Exception as e:
    print(f"⚠️ Error: {e}")

conn.commit()
conn.close()