import io
p = "app.py"
s = io.open(p, encoding="utf-8").read()
s = s.replace('os.environ.get("FLASK_RUN_HOST", "127.0.0.1")', 'os.environ.get("FLASK_RUN_HOST", "0.0.0.0")')
s = s.replace('os.environ.get("FLASK_DEBUG", "true")', 'os.environ.get("FLASK_DEBUG", "false")')
io.open(p, "w", encoding="utf-8").write(s)
print("done")
