# Launch Instruction

```
bash -c "cd /var/www/html/backend && source venv/bin/activate && nohup uvicorn main:app --host 0.0.0.0 --port 8000 > api.log 2>&1 &"
/var/www/html/backend/venv/bin/python3 /var/www/html/backend/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
```
