from __future__ import annotations

from datetime import datetime

from flask_login import UserMixin

from . import db, login_manager


# ==========================
# ユーザー
# ==========================
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    # "admin" or "student"
    role = db.Column(db.String(20), nullable=False, default="student")

    enrollments = db.relationship("Enrollment", back_populates="user")
    lesson_progress = db.relationship("LessonProgress", back_populates="user")
    quiz_results = db.relationship("QuizResult", back_populates="user")
    profile = db.relationship(
        "UserProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<User {self.username}>"

    @property
    def display_name(self) -> str:
        """表示名（プロフィールに設定があればそれ、なければ username）"""
        if self.profile and self.profile.display_name:
            return self.profile.display_name
        return self.username


@login_manager.user_loader
def load_user(user_id: str):
    return User.query.get(int(user_id))


# ==========================
# プロフィール
# ==========================
class UserProfile(db.Model):
    __tablename__ = "user_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True
    )
    display_name = db.Column(db.String(100), nullable=True)
    avatar_filename = db.Column(db.String(255), nullable=True)

    # 👇 追加：今週の目標レッスン数（未設定は NULL）
    weekly_goal_lessons = db.Column(db.Integer, nullable=True)

    user = db.relationship("User", back_populates="profile")

# ==========================
# コース & レッスン
# ==========================
class Course(db.Model):
    __tablename__ = "courses"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    thumbnail_filename = db.Column(db.String(255), nullable=True)

    category = db.Column(db.String(50), nullable=True)
    level = db.Column(db.String(20), nullable=True)

    # 修正：backref → back_populates に変更！
    lessons = db.relationship(
        "Lesson",
        back_populates="course",
        cascade="all, delete-orphan",
        lazy=True,
    )

    # Enrollment と紐付いてるなら必要
    enrollments = db.relationship("Enrollment", back_populates="course")

class Lesson(db.Model):
    __tablename__ = "lessons"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=True)
    sort_order = db.Column(db.Integer, default=1)

    # 修正：back_populates に統一
    course = db.relationship("Course", back_populates="lessons")

    progress = db.relationship(
        "LessonProgress", back_populates="lesson", cascade="all, delete-orphan"
    )

    quiz_questions = db.relationship(
        "QuizQuestion", back_populates="lesson", cascade="all, delete-orphan"
    )
    quiz_results = db.relationship(
        "QuizResult", back_populates="lesson", cascade="all, delete-orphan"
    )



class Enrollment(db.Model):
    __tablename__ = "enrollments"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    enrolled_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship("User", back_populates="enrollments")
    course = db.relationship("Course", back_populates="enrollments")


class LessonProgress(db.Model):
    __tablename__ = "lesson_progress"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    lesson_id = db.Column(db.Integer, db.ForeignKey("lessons.id"), nullable=False)
    is_completed = db.Column(db.Boolean, nullable=False, default=False)
    completed_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", back_populates="lesson_progress")
    lesson = db.relationship("Lesson", back_populates="progress")


# ==========================
# クイズ：問題・選択肢・結果
# ==========================

class QuizQuestion(db.Model):
    __tablename__ = "quiz_questions"

    id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey("lessons.id"), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=1)
    explanation = db.Column(db.Text, nullable=True)  # 解説

    lesson = db.relationship("Lesson", back_populates="quiz_questions")
    choices = db.relationship(
        "QuizChoice", back_populates="question", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<QuizQuestion {self.id}>"


class QuizChoice(db.Model):
    __tablename__ = "quiz_choices"

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey("quiz_questions.id"), nullable=False)
    choice_text = db.Column(db.String(255), nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False, default=False)

    question = db.relationship("QuizQuestion", back_populates="choices")

    def __repr__(self) -> str:
        return f"<QuizChoice {self.id}>"


class QuizResult(db.Model):
    __tablename__ = "quiz_results"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    lesson_id = db.Column(db.Integer, db.ForeignKey("lessons.id"), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    total_questions = db.Column(db.Integer, nullable=False)
    taken_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship("User", back_populates="quiz_results")
    lesson = db.relationship("Lesson", back_populates="quiz_results")

    # ★ 追加：この結果に紐づく 1問ごとの解答
    details = db.relationship(
        "QuizResultDetail",
        back_populates="result",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<QuizResult user={self.user_id} "
            f"lesson={self.lesson_id} score={self.score}>"
        )


# ★★★ 新規追加：クイズ結果の詳細（1問ごとの解答） ★★★
class QuizResultDetail(db.Model):
    __tablename__ = "quiz_result_details"

    id = db.Column(db.Integer, primary_key=True)

    result_id = db.Column(
        db.Integer,
        db.ForeignKey("quiz_results.id"),
        nullable=False,
    )
    question_id = db.Column(
        db.Integer,
        db.ForeignKey("quiz_questions.id"),
        nullable=False,
    )
    choice_id = db.Column(
        db.Integer,
        db.ForeignKey("quiz_choices.id"),
        nullable=False,
    )

    is_correct = db.Column(db.Boolean, nullable=False, default=False)

    # リレーション
    result = db.relationship("QuizResult", back_populates="details")
    question = db.relationship("QuizQuestion")
    choice = db.relationship("QuizChoice")

    def __repr__(self) -> str:
        return f"<QuizResultDetail result={self.result_id} q={self.question_id}>"

