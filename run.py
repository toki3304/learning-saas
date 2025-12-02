import os
from app import create_app

# Flaskアプリを生成
app = create_app()

if __name__ == "__main__":
    # Render が渡してくる PORT を使う（なければローカル用に5000）
    port = int(os.environ.get("PORT", 5000))
    # 0.0.0.0 で待ち受けて外部からアクセス可能にする
    app.run(host="0.0.0.0", port=port)
