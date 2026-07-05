import sqlite3

# Connect to the database file
conn = sqlite3.connect('D:\github_repo\legal-chatbot-ai\data\chroma\chroma.sqlite3')
cursor = conn.cursor()

# Execute a query and fetch results
cursor.execute("SELECT * FROM 'legal-insurance-db';")
rows = cursor.fetchall()

for row in rows:
    print(row)

# Clean up
conn.close()