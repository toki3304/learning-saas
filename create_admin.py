from werkzeug.security import generate_password_hash

from app import create_app, db
from app.models import User, UserProfile

app = create_app()

with app.app_context():
    # すでに同じユーザーがいれば何もしない
    user = User.query.filter_by(username="admin").first()
    if user:
        print("admin はすでに存在します")
    else:
        user = User(
            username="admin",
            email="admin@example.com",
            password_hash=generate_password_hash("admin1234"),
            role="admin",
        )
        db.session.add(user)
        db.session.commit()

        # プロフィールもついでに作成
        profile = UserProfile(user_id=user.id, display_name="admin")
        db.session.add(profile)
        db.session.commit()

        print("admin ユーザーを作成しました")
        print("  ログインID: admin@example.com")
        print("  パスワード: admin1234")
