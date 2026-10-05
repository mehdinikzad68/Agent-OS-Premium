import json
import sqlite3
conn = sqlite3.connect('/home/mehdi/workspace/Agent-OS/control-service/.logs/agent_os_kanban.db')
c = conn.cursor()
c.execute("SELECT payload FROM events WHERE job_id = 'job-fd928442f606' AND kind = 'job.completed_verified'")
row = c.fetchone()
print(row[0])