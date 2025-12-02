import os
from app import app  # もともと書いてある import はそのままでOK

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))  # Render の PORT を使う
    app.run(host="0.0.0.0", port=port)         