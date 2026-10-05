import json
import sqlite3
conn = sqlite3.connect('/home/mehdi/workspace/Agent-OS/control-service/.logs/agent_os_kanban.db')
c = conn.cursor()
c.execute("SELECT evidence FROM work_items WHERE job_id = 'job-fd928442f606' ORDER BY sequence_number DESC LIMIT 1")
row = c.fetchone()
print(row[0])
