from __future__ import annotations
from sqlalchemy import or_
from flask import abort
from datetime import datetime, date, timedelta

import os
import re

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    request,
    flash,
    current_app,
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from markupsafe import Markup, escape

from . import db
from .models import (
    Course,
    Lesson,
    Enrollment,
    LessonProgress,
    QuizQuestion,
    QuizChoice,
    QuizResult,
    UserProfile,
    QuizResultDetail,
)

bp = Blueprint("main", __name__)


# -------------------------
# ユーザーごとの進捗マップ作成
# -------------------------
def _build_progress_map(courses, user):
    """コースごとの進捗情報を dict で返す"""
    progress_map: dict[int, dict] = {}

    if not getattr(user, "is_authenticated", False):
        return progress_map

    for course in courses:
        total_lessons = Lesson.query.filter_by(course_id=course.id).count()
        if total_lessons == 0:
            progress_map[course.id] = {
                "completed": 0,
                "total": 0,
                "percent": 0,
                "is_completed": False,
            }
            continue

        completed_count = (
            LessonProgress.query
            .join(Lesson, LessonProgress.lesson_id == Lesson.id)
            .filter(
                Lesson.course_id == course.id,
                LessonProgress.user_id == user.id,
                LessonProgress.is_completed.is_(True),
            )
            .count()
        )

        percent = int(completed_count / total_lessons * 100)
        is_completed = (completed_count == total_lessons)

        progress_map[course.id] = {
            "completed": completed_count,
            "total": total_lessons,
            "percent": percent,
            "is_completed": is_completed,
        }

    return progress_map


# -------------------------
# レッスン本文リッチ表示フィルタ
# [[image:ファイル名]], [[youtube:URL]] を変換
# -------------------------
@bp.app_template_filter("rich_lesson")
def rich_lesson(text: str | None) -> Markup:
    """
    レッスン本文中の
      [[image:foo.png]]
      [[youtube:https://www.youtube.com/watch?v=XXXX]]
    をHTMLに変換する。
    それ以外のテキストはエスケープして安全に表示。
    """
    if not text:
        return Markup("")

    pattern = re.compile(r"\[\[(image|youtube):([^\]]+)\]\]")
    result_parts: list[str | Markup] = []
    last = 0

    s = text

    from flask import url_for  # フィルタ内で使う

    for m in pattern.finditer(s):
        # 通常テキスト部分
        before = s[last : m.start()]
        if before:
            result_parts.append(escape(before))

        kind = m.group(1)
        value = m.group(2).strip()

        if kind == "image":
            # static/uploads/lessons/ 以下の画像を表示
            src = url_for("static", filename=f"uploads/lessons/{value}")
            html = (
                f'<img src="{src}" alt="{escape(value)}" '
                f'style="max-width:100%;height:auto;margin:0.5rem 0;">'
            )
            result_parts.append(Markup(html))

        elif kind == "youtube":
            url = value
            video_id = None

            if "watch?v=" in url:
                video_id = url.split("watch?v=")[-1].split("&")[0]
            elif "youtu.be/" in url:
                video_id = url.split("youtu.be/")[-1].split("?")[0]

            if video_id:
                embed_src = f"https://www.youtube.com/embed/{video_id}"
            else:
                embed_src = url  # うまく取れなかった場合はそのまま

            iframe = f"""
<div class="ratio ratio-16x9 my-2">
  <iframe
    src="{embed_src}"
    title="YouTube video"
    allowfullscreen
  ></iframe>
</div>
"""
            result_parts.append(Markup(iframe))

        last = m.end()

    # 最後の残りテキスト
    tail = s[last:]
    if tail:
        result_parts.append(escape(tail))

    html_all = "".join(str(p) for p in result_parts)
    # 改行は <br> に変換
    html_all = html_all.replace("\n", "<br>\n")
    return Markup(html_all)


# ===========================
# トップ / コース一覧（検索付き）
# ===========================
@bp.route("/")
def index():
    """トップページ（コース一覧 + 検索＆カテゴリ/レベル絞り込み）"""
    q = (request.args.get("q") or "").strip()
    selected_category = request.args.get("category") or ""
    selected_level = request.args.get("level") or ""

    # ベースのクエリ
    query = Course.query.order_by(Course.created_at.desc())

    # キーワード検索（タイトル・説明）
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Course.title.ilike(like),
                Course.description.ilike(like),
            )
        )

    # カテゴリ絞り込み
    if selected_category:
        query = query.filter(Course.category == selected_category)

    # レベル絞り込み
    if selected_level:
        query = query.filter(Course.level == selected_level)

    courses = query.all()

    # セレクトボックス用に、存在するカテゴリ＆レベルをDistinctで取得
    all_categories = [
        row[0]
        for row in db.session.query(Course.category)
        .distinct()
        .order_by(Course.category.asc())
        .all()
        if row[0]
    ]
    all_levels = [
        row[0]
        for row in db.session.query(Course.level)
        .distinct()
        .order_by(Course.level.asc())
        .all()
        if row[0]
    ]

    # 進捗マップ
    progress_map = {}
    if current_user.is_authenticated:
        progress_map = _build_progress_map(courses, current_user)

    return render_template(
        "index.html",
        courses=courses,
        progress_map=progress_map,
        q=q,
        categories=all_categories,
        levels=all_levels,
        selected_category=selected_category,
        selected_level=selected_level,
    )

@bp.route("/courses")
def course_list():
    # `/?q=...` と同じ検索ロジック
    q = request.args.get("q", "").strip()

    query = Course.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Course.title.ilike(like),
                Course.description.ilike(like),
            )
        )

    courses = query.order_by(Course.created_at.desc()).all()
    progress_map = _build_progress_map(courses, current_user)

    return render_template(
        "index.html",
        courses=courses,
        progress_map=progress_map,
        q=q,
    )

@bp.route("/courses/<int:course_id>/certificate")
@login_required
def course_certificate(course_id: int):
    """コース修了証の表示（全レッスンを完了したユーザーのみ）"""
    course = Course.query.get_or_404(course_id)

    # 受講しているかチェック
    enrollment = Enrollment.query.filter_by(
        user_id=current_user.id,
        course_id=course.id,
    ).first()
    if not enrollment:
        flash("このコースを受講していません。", "warning")
        return redirect(url_for("main.course_detail", course_id=course.id))

    # レッスン一覧
    lessons = course.lessons
    if not lessons:
        flash("このコースにはレッスンがまだありません。", "warning")
        return redirect(url_for("main.course_detail", course_id=course.id))

    lesson_ids = [l.id for l in lessons]

    # 完了したレッスン数
    q = (
        LessonProgress.query
        .filter(LessonProgress.user_id == current_user.id)
        .filter(LessonProgress.lesson_id.in_(lesson_ids))
        .filter(LessonProgress.is_completed == True)
    )
    completed_count = q.count()
    total_count = len(lesson_ids)

    if completed_count < total_count:
        flash("このコースはまだ修了していません。", "warning")
        return redirect(url_for("main.course_detail", course_id=course.id))

    # 修了日＝最後に完了したレッスンの日付
    latest_progress = q.order_by(LessonProgress.completed_at.desc()).first()
    completed_at = latest_progress.completed_at if latest_progress else None

    return render_template(
        "courses/certificate.html",
        course=course,
        completed_at=completed_at,
    )

@bp.route("/dashboard")
@login_required
def dashboard():
    # 受講中コース
    enrollments = Enrollment.query.filter_by(user_id=current_user.id).all()
    course_ids = [e.course_id for e in enrollments]
    courses = Course.query.filter(Course.id.in_(course_ids)).all() if course_ids else []

    progress_map = _build_progress_map(courses, current_user)

    total_courses = len(courses)
    total_lessons_completed = LessonProgress.query.filter_by(
        user_id=current_user.id,
        is_completed=True,
    ).count()
    total_quizzes = QuizResult.query.filter_by(user_id=current_user.id).count()

    # 完了コース数
    completed_courses = 0
    for c in courses:
        p = progress_map.get(c.id)
        if p and p.get("is_completed"):
            completed_courses += 1

    # 最近のクイズ結果（5件）
    latest_results = (
        QuizResult.query
        .filter_by(user_id=current_user.id)
        .order_by(QuizResult.taken_at.desc())
        .limit(5)
        .all()
    )

    # 🔹 追加：最近完了したレッスン（5件）
    recent_lessons = (
        LessonProgress.query
        .join(Lesson)
        .join(Course)
        .filter(
            LessonProgress.user_id == current_user.id,
            LessonProgress.is_completed.is_(True),
        )
        .order_by(LessonProgress.completed_at.desc())
        .limit(5)
        .all()
    )

    # ====== 今日・今週・平均スコア ======
    today = datetime.utcnow().date()
    start_of_today = datetime(today.year, today.month, today.day)

    weekday = today.weekday()  # 0: 月, 6: 日
    start_of_week_date = today - timedelta(days=weekday)
    start_of_week = datetime(
        start_of_week_date.year,
        start_of_week_date.month,
        start_of_week_date.day,
    )

    # 今日完了したレッスン
    today_completed_lessons = (
        LessonProgress.query
        .filter_by(user_id=current_user.id, is_completed=True)
        .filter(LessonProgress.completed_at >= start_of_today)
        .count()
    )

    # 今週完了したレッスン
    week_completed_lessons = (
        LessonProgress.query
        .filter_by(user_id=current_user.id, is_completed=True)
        .filter(LessonProgress.completed_at >= start_of_week)
        .count()
    )

    # クイズ平均スコア（％）
    all_quiz_results = QuizResult.query.filter_by(user_id=current_user.id).all()
    total_correct = sum(r.score for r in all_quiz_results)
    total_questions = sum(r.total_questions for r in all_quiz_results)
    avg_quiz_score = 0
    if total_questions > 0:
        avg_quiz_score = int(total_correct / total_questions * 100)

    # ====== 直近7日間の「日ごとの完了レッスン数」 ======
    start_chart_date = today - timedelta(days=6)
    start_chart = datetime(
        start_chart_date.year,
        start_chart_date.month,
        start_chart_date.day,
    )

    recent_progress = (
        LessonProgress.query
        .filter_by(user_id=current_user.id, is_completed=True)
        .filter(LessonProgress.completed_at >= start_chart)
        .all()
    )

    counts_by_date: dict[date, int] = {}
    for p in recent_progress:
        if not p.completed_at:
            continue
        d = p.completed_at.date()
        if d < start_chart_date or d > today:
            continue
        counts_by_date[d] = counts_by_date.get(d, 0) + 1

    # グラフ用ラベルと値（古い日→新しい日）
    chart_labels: list[str] = []
    chart_values: list[int] = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        chart_labels.append(d.strftime("%m/%d"))
        chart_values.append(counts_by_date.get(d, 0))

    # ====== 連続学習日数（ストリーク） ======
    streak_start_date = today - timedelta(days=59)
    streak_start = datetime(
        streak_start_date.year,
        streak_start_date.month,
        streak_start_date.day,
    )

    streak_progress = (
        LessonProgress.query
        .filter_by(user_id=current_user.id, is_completed=True)
        .filter(LessonProgress.completed_at >= streak_start)
        .all()
    )

    learned_dates = {
        p.completed_at.date()
        for p in streak_progress
        if p.completed_at is not None
    }

    # 現在のストリーク
    current_streak_days = 0
    d = today
    while d in learned_dates:
        current_streak_days += 1
        d -= timedelta(days=1)

    # 過去最長ストリーク
    longest_streak_days = 0
    if learned_dates:
        streak = 0
        prev = None
        for d in sorted(learned_dates):
            if prev is None or (d - prev).days > 1:
                streak = 1
            else:
                streak += 1
            if streak > longest_streak_days:
                longest_streak_days = streak
            prev = d

    # ====== 今週の目標達成率 ======
    weekly_goal = 0
    weekly_goal_percent = None

    if current_user.profile:
        goal_val = getattr(current_user.profile, "weekly_goal_lessons", None)
        if goal_val is not None:
            weekly_goal = goal_val or 0

    if weekly_goal > 0:
        weekly_goal_percent = int(
            min(100, week_completed_lessons * 100 / weekly_goal)
        )

    return render_template(
        "dashboard.html",
        courses=courses,
        progress_map=progress_map,
        total_courses=total_courses,
        total_lessons_completed=total_lessons_completed,
        total_quizzes=total_quizzes,
        completed_courses=completed_courses,
        latest_results=latest_results,        # 👈 複数形に戻す
        recent_lessons=recent_lessons,
        today_completed_lessons=today_completed_lessons,
        week_completed_lessons=week_completed_lessons,
        avg_quiz_score=avg_quiz_score,
        chart_labels=chart_labels,
        chart_values=chart_values,
        current_streak_days=current_streak_days,
        longest_streak_days=longest_streak_days,
        weekly_goal=weekly_goal,
        weekly_goal_percent=weekly_goal_percent,
    )


# ===========================
# 学習履歴
# ===========================
@bp.route("/history")
@login_required
def history():
    """学習履歴ページ（コース & 期間フィルタ付き）"""

    # --- フィルタ入力 ---
    selected_course_id = request.args.get("course_id", type=int)
    start_date_str = request.args.get("start_date") or ""
    end_date_str = request.args.get("end_date") or ""

    # 自分が受講しているコース（セレクトボックス用）
    enrollments = Enrollment.query.filter_by(user_id=current_user.id).all()
    courses = [e.course for e in enrollments]

    # 共通の日時条件を作成
    start_dt = None
    end_dt = None

    # start_date_str, end_date_str は "YYYY-MM-DD" の想定
    try:
        if start_date_str:
            d = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            start_dt = datetime(d.year, d.month, d.day)
        if end_date_str:
            d = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            # 終了日はその日の終わりまで含めたいので +1日した0時を「<」で判定
            d_next = d + timedelta(days=1)
            end_dt = datetime(d_next.year, d_next.month, d_next.day)
    except ValueError:
        # 日付フォーマットがおかしいときは無視して全期間扱い
        start_dt = None
        end_dt = None

    # --- レッスン履歴クエリ ---
    lesson_q = (
        LessonProgress.query
        .join(Lesson)
        .join(Course)
        .filter(LessonProgress.user_id == current_user.id)
        .filter(LessonProgress.is_completed.is_(True))
    )

    if selected_course_id:
        lesson_q = lesson_q.filter(Course.id == selected_course_id)
    if start_dt:
        lesson_q = lesson_q.filter(LessonProgress.completed_at >= start_dt)
    if end_dt:
        lesson_q = lesson_q.filter(LessonProgress.completed_at < end_dt)

    recent_lessons = (
        lesson_q
        .order_by(LessonProgress.completed_at.desc())
        .limit(50)
        .all()
    )

    # --- クイズ履歴クエリ ---
    quiz_q = (
        QuizResult.query
        .join(Lesson)
        .join(Course)
        .filter(QuizResult.user_id == current_user.id)
    )

    if selected_course_id:
        quiz_q = quiz_q.filter(Course.id == selected_course_id)
    if start_dt:
        quiz_q = quiz_q.filter(QuizResult.taken_at >= start_dt)
    if end_dt:
        quiz_q = quiz_q.filter(QuizResult.taken_at < end_dt)

    recent_quiz_results = (
        quiz_q
        .order_by(QuizResult.taken_at.desc())
        .limit(50)
        .all()
    )

    return render_template(
        "history.html",
        courses=courses,
        recent_lessons=recent_lessons,
        recent_quiz_results=recent_quiz_results,
        selected_course_id=selected_course_id,
        start_date_str=start_date_str,
        end_date_str=end_date_str,
    )

# ===========================
# クイズ成績サマリー（ユーザー自身）
# ===========================
@bp.route("/quiz_summary")
@login_required
def quiz_summary():
    """自分のクイズ成績をレッスンごとに集計して表示"""

    # 自分の全クイズ結果（レッスン付き）
    results = (
        QuizResult.query
        .filter_by(user_id=current_user.id)
        .join(Lesson)
        .join(Course)
        .order_by(QuizResult.taken_at.desc())
        .all()
    )

    # lesson_id ごとに集計
    summary_by_lesson: dict[int, dict] = {}

    for r in results:
        lid = r.lesson_id
        if lid not in summary_by_lesson:
            summary_by_lesson[lid] = {
                "lesson": r.lesson,
                "course": r.lesson.course,
                "attempts": 0,
                "best_score": 0,
                "best_percent": 0,
                "total_questions": r.total_questions,
                "last_taken_at": None,
                "latest_result": r,  # 最新の結果（順序的に最初に来るのが最新）
            }

        entry = summary_by_lesson[lid]
        entry["attempts"] += 1

        # ベストスコア更新
        if r.score > entry["best_score"]:
            entry["best_score"] = r.score
            entry["total_questions"] = r.total_questions
            if r.total_questions > 0:
                entry["best_percent"] = int(r.score / r.total_questions * 100)

        # 最終受験日時（結果は taken_at desc で並べてあるので、最初が最新だが一応チェック）
        if entry["last_taken_at"] is None or r.taken_at > entry["last_taken_at"]:
            entry["last_taken_at"] = r.taken_at
            entry["latest_result"] = r

    # 表示用にリストへ（コース / レッスン名でソート）
    summary_list = sorted(
        summary_by_lesson.values(),
        key=lambda x: (x["course"].title, x["lesson"].sort_order),
    )

    return render_template(
        "quiz_summary.html",
        summary_list=summary_list,
    )

# ===========================
# プロフィール表示・編集
# ===========================
@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    profile = current_user.profile
    if not profile:
        profile = UserProfile(user_id=current_user.id)
        db.session.add(profile)
        db.session.commit()

    if request.method == "POST":
        # 表示名
        display_name = request.form.get("display_name", "").strip()
        if display_name:
            profile.display_name = display_name

        # 👇 今週の目標レッスン数
        goal_raw = request.form.get("weekly_goal_lessons", "").strip()
        if goal_raw != "":
            try:
                goal_val = int(goal_raw)
                if goal_val < 0:
                    raise ValueError
            except ValueError:
                flash("今週の目標レッスン数は 0 以上の整数で入力してください。", "danger")
                return redirect(url_for("main.profile"))
            profile.weekly_goal_lessons = goal_val
        else:
            # 空欄なら「未設定」（NULL）に戻す
            profile.weekly_goal_lessons = None

        # アイコン画像アップロード
        file = request.files.get("avatar")
        if file and file.filename:
            filename = secure_filename(file.filename)
            _, ext = os.path.splitext(filename)
            ext = ext.lower()
            if ext not in {".png", ".jpg", ".jpeg", ".gif"}:
                flash(
                    "画像ファイル（png / jpg / jpeg / gif）だけアップロードできます。",
                    "danger",
                )
            else:
                upload_dir = os.path.join(
                    current_app.root_path, "static", "uploads", "avatars"
                )
                os.makedirs(upload_dir, exist_ok=True)

                new_name = f"user{current_user.id}{ext}"
                file_path = os.path.join(upload_dir, new_name)
                file.save(file_path)

                profile.avatar_filename = new_name

        db.session.commit()
        flash("プロフィールを更新しました。", "success")
        return redirect(url_for("main.profile"))

    return render_template("profile.html", profile=profile)

# ===========================
# 管理者用：コース作成（サムネ付き）
# ===========================
@bp.route("/courses/create", methods=["GET", "POST"])
@login_required
def create_course():
    if current_user.role != "admin":
        flash("コース作成は管理者のみ可能です。", "danger")
        return redirect(url_for("main.index"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        category = request.form.get("category", "").strip() or None
        level = request.form.get("level", "").strip() or None

        if not title:
            flash("タイトルは必須です。", "danger")
            return redirect(url_for("main.create_course"))

        # サムネ画像
        thumbnail_file = request.files.get("thumbnail")
        thumbnail_filename = None

        if thumbnail_file and thumbnail_file.filename:
            filename = secure_filename(thumbnail_file.filename)
            _, ext = os.path.splitext(filename)
            ext = ext.lower()
            if ext not in {".png", ".jpg", ".jpeg", ".gif"}:
                flash(
                    "サムネ画像は png / jpg / jpeg / gif のみアップロードできます。",
                    "danger",
                )
                return redirect(url_for("main.create_course"))

            upload_dir = os.path.join(
                current_app.root_path, "static", "uploads", "courses"
            )
            os.makedirs(upload_dir, exist_ok=True)

            ts = int(datetime.utcnow().timestamp())
            thumbnail_filename = f"course_{ts}{ext}"
            file_path = os.path.join(upload_dir, thumbnail_filename)
            thumbnail_file.save(file_path)

        course = Course(
            title=title,
            description=description,
            thumbnail_filename=thumbnail_filename,
            category=category,
            level=level,
        )
        db.session.add(course)
        db.session.commit()

        flash("コースを作成しました。", "success")
        return redirect(url_for("main.course_detail", course_id=course.id))

    return render_template("courses/create.html")



# ===========================
# コース詳細
# ===========================
@bp.route("/courses/<int:course_id>")
@login_required
def course_detail(course_id: int):
    course = Course.query.get_or_404(course_id)
    lessons = Lesson.query.filter_by(course_id=course.id).order_by(Lesson.sort_order).all()

    enrollment = Enrollment.query.filter_by(
        user_id=current_user.id, course_id=course.id
    ).first()

    progress_map: dict[int, bool] = {}
    if enrollment:
        progresses = LessonProgress.query.filter_by(user_id=current_user.id).all()
        for p in progresses:
            progress_map[p.lesson_id] = p.is_completed

    # コース完了判定（全レッスン完了）
    course_completed = False
    if lessons:
        course_completed = all(progress_map.get(lesson.id) for lesson in lessons)

    return render_template(
        "courses/detail.html",
        course=course,
        lessons=lessons,
        enrollment=enrollment,
        progress_map=progress_map,
        course_completed=course_completed,
    )


# ===========================
# 受講登録
# ===========================
@bp.route("/courses/<int:course_id>/enroll", methods=["POST"])
@login_required
def enroll_course(course_id: int):
    course = Course.query.get_or_404(course_id)

    if Enrollment.query.filter_by(user_id=current_user.id, course_id=course.id).first():
        flash("すでに受講登録済みです。", "info")
        return redirect(url_for("main.course_detail", course_id=course.id))

    enrollment = Enrollment(user_id=current_user.id, course_id=course.id)
    db.session.add(enrollment)
    db.session.commit()

    flash("コースに受講登録しました。", "success")
    return redirect(url_for("main.course_detail", course_id=course.id))


# ===========================
# レッスン作成（管理者）
# ===========================
@bp.route("/courses/<int:course_id>/lessons/create", methods=["GET", "POST"])
@login_required
def create_lesson(course_id: int):
    if current_user.role != "admin":
        flash("レッスン作成は管理者のみ可能です。", "danger")
        return redirect(url_for("main.course_detail", course_id=course_id))

    course = Course.query.get_or_404(course_id)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        sort_order = int(request.form.get("sort_order", 1))

        if not title:
            flash("タイトルは必須です。", "danger")
            return redirect(url_for("main.create_lesson", course_id=course_id))

        lesson = Lesson(
            course_id=course.id,
            title=title,
            content=content,
            sort_order=sort_order,
        )
        db.session.add(lesson)
        db.session.commit()

        flash("レッスンを作成しました。", "success")
        return redirect(url_for("main.course_detail", course_id=course.id))

    return render_template("courses/create_lesson.html", course=course)


# ===========================
# レッスン詳細（本文表示）
# ===========================
@bp.route("/lessons/<int:lesson_id>")
@login_required
def lesson_detail(lesson_id: int):
    lesson = Lesson.query.get_or_404(lesson_id)
    course = lesson.course

    if current_user.role != "admin":
        enrollment = Enrollment.query.filter_by(
            user_id=current_user.id, course_id=course.id
        ).first()
        if not enrollment:
            flash("このコースを受講登録していません。", "danger")
            return redirect(url_for("main.course_detail", course_id=course.id))

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id,
    ).first()
    is_completed = bool(progress and progress.is_completed)

    next_lesson = (
        Lesson.query.filter(
            Lesson.course_id == course.id,
            Lesson.sort_order > lesson.sort_order,
        )
        .order_by(Lesson.sort_order.asc())
        .first()
    )

    quiz_count = QuizQuestion.query.filter_by(lesson_id=lesson.id).count()
    latest_result = None
    if current_user.is_authenticated:
        latest_result = (
            QuizResult.query.filter_by(user_id=current_user.id, lesson_id=lesson.id)
            .order_by(QuizResult.taken_at.desc())
            .first()
        )

    return render_template(
        "courses/lesson.html",
        course=course,
        lesson=lesson,
        is_completed=is_completed,
        next_lesson=next_lesson,
        quiz_count=quiz_count,
        latest_result=latest_result,
    )


# ===========================
# レッスン用画像アップロード（管理者）
# ===========================
@bp.route("/lessons/<int:lesson_id>/assets", methods=["GET", "POST"])
@login_required
def lesson_assets(lesson_id: int):
    if current_user.role != "admin":
        flash("レッスン素材の管理は管理者のみ可能です。", "danger")
        return redirect(url_for("main.lesson_detail", lesson_id=lesson_id))

    lesson = Lesson.query.get_or_404(lesson_id)

    upload_dir = os.path.join(current_app.root_path, "static", "uploads", "lessons")
    os.makedirs(upload_dir, exist_ok=True)

    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            flash("ファイルを選択してください。", "danger")
            return redirect(url_for("main.lesson_assets", lesson_id=lesson.id))

        filename = secure_filename(file.filename)
        _, ext = os.path.splitext(filename)
        ext = ext.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".gif"}:
            flash(
                "画像ファイル（png / jpg / jpeg / gif）のみアップロードできます。",
                "danger",
            )
            return redirect(url_for("main.lesson_assets", lesson_id=lesson.id))

        ts = int(datetime.utcnow().timestamp())
        new_name = f"lesson{lesson.id}_{ts}{ext}"
        file_path = os.path.join(upload_dir, new_name)
        file.save(file_path)

        flash(f"画像をアップロードしました。本文では [[image:{new_name}]] と書いて使えます。", "success")
        return redirect(url_for("main.lesson_assets", lesson_id=lesson.id))

    # このレッスン用の画像一覧（ファイル名が lesson{lesson.id}_ で始まるもの）
    files: list[str] = []
    if os.path.isdir(upload_dir):
        for fname in sorted(os.listdir(upload_dir)):
            if fname.startswith(f"lesson{lesson.id}_"):
                files.append(fname)

    return render_template("courses/lesson_assets.html", lesson=lesson, files=files)


# ===========================
# レッスン完了
# ===========================
@bp.route("/lessons/<int:lesson_id>/complete", methods=["POST"])
@login_required
def complete_lesson(lesson_id: int):
    lesson = Lesson.query.get_or_404(lesson_id)
    enrollment = Enrollment.query.filter_by(
        user_id=current_user.id, course_id=lesson.course_id
    ).first()
    if not enrollment:
        flash("このコースを受講登録していません。", "danger")
        return redirect(url_for("main.course_detail", course_id=lesson.course_id))

    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id,
    ).first()

    if not progress:
        progress = LessonProgress(
            user_id=current_user.id,
            lesson_id=lesson.id,
            is_completed=True,
            completed_at=datetime.utcnow(),
        )
        db.session.add(progress)
    else:
        progress.is_completed = True
        progress.completed_at = datetime.utcnow()

    db.session.commit()
    flash("レッスンを完了にしました。", "success")
    return redirect(url_for("main.lesson_detail", lesson_id=lesson.id))


# ===========================
# クイズ管理（管理者用）
# ===========================
@bp.route("/lessons/<int:lesson_id>/quiz/manage")
@login_required
def quiz_manage(lesson_id: int):
    if current_user.role != "admin":
        flash("クイズ管理は管理者のみ可能です。", "danger")
        return redirect(url_for("main.lesson_detail", lesson_id=lesson_id))

    lesson = Lesson.query.get_or_404(lesson_id)
    questions = (
        QuizQuestion.query
        .filter_by(lesson_id=lesson.id)
        .order_by(QuizQuestion.sort_order)
        .all()
    )

    return render_template(
        "courses/quiz_manage.html",
        lesson=lesson,
        questions=questions,
    )


@bp.route("/lessons/<int:lesson_id>/quiz/create", methods=["GET", "POST"])
@login_required
def quiz_create(lesson_id: int):
    """クイズ問題の作成（管理者用）"""
    if current_user.role != "admin":
        flash("クイズ作成は管理者のみ可能です。", "danger")
        return redirect(url_for("main.lesson_detail", lesson_id=lesson_id))

    lesson = Lesson.query.get_or_404(lesson_id)

    if request.method == "POST":
        question_text = request.form.get("question_text", "").strip()
        explanation = request.form.get("explanation", "").strip()
        sort_order = int(request.form.get("sort_order", 1))

        choices_text = [
            request.form.get("choice1", "").strip(),
            request.form.get("choice2", "").strip(),
            request.form.get("choice3", "").strip(),
            request.form.get("choice4", "").strip(),
        ]
        correct_index = request.form.get("correct_choice")

        # バリデーション
        if not question_text:
            flash("問題文は必須です。", "danger")
            return redirect(url_for("main.quiz_create", lesson_id=lesson_id))

        if not correct_index:
            flash("正解の選択肢を選んでください。", "danger")
            return redirect(url_for("main.quiz_create", lesson_id=lesson_id))

        try:
            correct_index = int(correct_index)
        except ValueError:
            flash("正解の選択肢の指定が不正です。", "danger")
            return redirect(url_for("main.quiz_create", lesson_id=lesson_id))

        if correct_index not in {1, 2, 3, 4}:
            flash("正解の選択肢の指定が不正です。", "danger")
            return redirect(url_for("main.quiz_create", lesson_id=lesson_id))

        # 問題本体の保存
        question = QuizQuestion(
            lesson_id=lesson.id,
            question_text=question_text,
            explanation=explanation,
            sort_order=sort_order,
        )
        db.session.add(question)
        db.session.flush()  # question.id を使うため

        # 選択肢の保存
        for i, text in enumerate(choices_text, start=1):
            if not text:
                continue
            choice = QuizChoice(
                question_id=question.id,
                choice_text=text,
                is_correct=(i == correct_index),
            )
            db.session.add(choice)

        db.session.commit()
        flash("クイズ問題を追加しました。", "success")
        return redirect(url_for("main.quiz_manage", lesson_id=lesson.id))

    return render_template("courses/quiz_create.html", lesson=lesson)


@bp.route("/questions/<int:question_id>/edit", methods=["GET", "POST"])
@login_required
def quiz_edit(question_id: int):
    """クイズ問題の編集（管理者用）"""
    if current_user.role != "admin":
        flash("クイズ編集は管理者のみ可能です。", "danger")
        return redirect(url_for("main.dashboard"))

    question = QuizQuestion.query.get_or_404(question_id)
    lesson = question.lesson

    if request.method == "POST":
        # フォームから値を取得
        question_text = request.form.get("question_text", "").strip()
        explanation = request.form.get("explanation", "").strip()
        sort_order_raw = request.form.get("sort_order", "1")

        choices_text = [
            request.form.get("choice1", "").strip(),
            request.form.get("choice2", "").strip(),
            request.form.get("choice3", "").strip(),
            request.form.get("choice4", "").strip(),
        ]
        correct_choice_raw = request.form.get("correct_choice")

        errors: list[str] = []

        # 並び順
        try:
            sort_order = int(sort_order_raw)
        except ValueError:
            sort_order = 1
            errors.append("並び順(sort_order)は数値で入力してください。")

        # 問題文チェック
        if not question_text:
            errors.append("問題文は必須です。")

        # 正解選択肢チェック
        if not correct_choice_raw:
            errors.append("正解の選択肢を1つ選んでください。")
            correct_index = 1  # 仮置き
        else:
            try:
                correct_index = int(correct_choice_raw)
                if correct_index not in {1, 2, 3, 4}:
                    errors.append("正解の選択肢の指定が不正です。")
            except ValueError:
                correct_index = 1
                errors.append("正解の選択肢の指定が不正です。")

        # 少なくとも1つは選択肢が必要
        if all(text == "" for text in choices_text):
            errors.append("少なくとも1つは選択肢を入力してください。")

        # エラーがあれば、そのまま同じテンプレートを再表示（入力値を保持）
        if errors:
            for msg in errors:
                flash(msg, "danger")

            return render_template(
                "courses/quiz_edit.html",
                lesson=lesson,
                question=question,
                choice_texts=choices_text,
                correct_index=locals().get("correct_index", 1),
            )

        # ここまできたらバリデーションOK → DB更新
        question.question_text = question_text
        question.explanation = explanation
        question.sort_order = sort_order

        # 既存の選択肢を一旦削除して作り直す（シンプル実装）
        QuizChoice.query.filter_by(question_id=question.id).delete()

        for i, text in enumerate(choices_text, start=1):
            if not text:
                continue
            choice = QuizChoice(
                question_id=question.id,
                choice_text=text,
                is_correct=(i == correct_index),
            )
            db.session.add(choice)

        db.session.commit()
        flash("クイズ問題を更新しました。", "success")
        return redirect(url_for("main.quiz_manage", lesson_id=lesson.id))

    # GET: 既存データをフォームに反映
    choices = (
        QuizChoice.query
        .filter_by(question_id=question.id)
        .order_by(QuizChoice.id.asc())
        .all()
    )

    choice_texts = ["", "", "", ""]
    correct_index = 1

    for i, c in enumerate(choices[:4]):
        choice_texts[i] = c.choice_text
        if c.is_correct:
            correct_index = i + 1

    return render_template(
        "courses/quiz_edit.html",
        lesson=lesson,
        question=question,
        choice_texts=choice_texts,
        correct_index=correct_index,
    )

@bp.route("/questions/<int:question_id>/delete", methods=["POST"])
@login_required
def quiz_delete(question_id: int):
    """クイズ問題の削除（管理者用）"""
    if current_user.role != "admin":
        flash("クイズ削除は管理者のみ可能です。", "danger")
        return redirect(url_for("main.dashboard"))

    question = QuizQuestion.query.get_or_404(question_id)
    lesson = question.lesson

    # 結果詳細に紐づいていても消してしまってOKという前提
    # もし成績を残したければ、論理削除フラグにする実装もあり。
    QuizChoice.query.filter_by(question_id=question.id).delete()
    db.session.delete(question)
    db.session.commit()

    flash("クイズ問題を削除しました。", "success")
    return redirect(url_for("main.quiz_manage", lesson_id=lesson.id))

@bp.route("/lessons/<int:lesson_id>/quiz/results_admin")
@login_required
def quiz_results_admin(lesson_id: int):
    """管理者用：このレッスンのクイズ結果一覧"""

    if current_user.role != "admin":
        flash("クイズ結果一覧は管理者のみ閲覧できます。", "danger")
        return redirect(url_for("main.lesson_detail", lesson_id=lesson_id))

    lesson = Lesson.query.get_or_404(lesson_id)
    course = lesson.course

    # このレッスンの全クイズ結果（新しい順）
    results = (
        QuizResult.query
        .filter_by(lesson_id=lesson.id)
        .order_by(QuizResult.taken_at.desc())
        .all()
    )

    # 受験回数などの集計（テンプレで使う用）
    total_attempts = len(results)
    avg_score = None
    if total_attempts > 0:
        avg_score = sum(r.score for r in results) / total_attempts

    return render_template(
        "courses/quiz_results_admin.html",
        lesson=lesson,
        course=course,
        results=results,
        total_attempts=total_attempts,  # ← これを追加
        avg_score=avg_score,            # （テンプレで使いたければ）
    )


# ===========================
# 管理者用：レッスン全体の問題ごとの正答率一覧
# ===========================
@bp.route("/lessons/<int:lesson_id>/quiz/stats")
@login_required
def quiz_lesson_stats(lesson_id: int):
    """管理者用：このレッスンの各問題の正答率＆選択肢の集計一覧"""

    if current_user.role != "admin":
        flash("クイズ統計は管理者のみ閲覧できます。", "danger")
        return redirect(url_for("main.lesson_detail", lesson_id=lesson_id))

    lesson = Lesson.query.get_or_404(lesson_id)
    course = lesson.course

    # このレッスンの全問題（並び順順）
    questions = (
        QuizQuestion.query
        .filter_by(lesson_id=lesson.id)
        .order_by(QuizQuestion.sort_order)
        .all()
    )

    # このレッスンの受験数（QuizResult 件数）
    total_results = (
        QuizResult.query
        .filter_by(lesson_id=lesson.id)
        .count()
    )

    stats_list = []

    for q in questions:
        # この問題への全回答
        details_q = QuizResultDetail.query.filter_by(question_id=q.id).all()

        total_answers = len(details_q)
        correct_answers = sum(1 for d in details_q if d.is_correct)
        correct_percent = (
            int(correct_answers * 100 / total_answers)
            if total_answers > 0 else None
        )

        # 選択肢ごとの選ばれた回数
        choice_items = []
        for ch in q.choices:
            count = sum(1 for d in details_q if d.choice_id == ch.id)
            choice_items.append({
                "choice": ch,
                "count": count,
            })

        stats_list.append({
            "question": q,
            "total_answers": total_answers,
            "correct_answers": correct_answers,
            "correct_percent": correct_percent,
            "choices": choice_items,
        })

    return render_template(
        "courses/lesson_quiz_stats.html",
        course=course,
        lesson=lesson,
        stats_list=stats_list,
        total_results=total_results,
    )

@bp.route("/quiz_results/<int:result_id>")
@login_required
def quiz_result_detail(result_id: int):
    """クイズ結果の詳細表示ページ"""

    # 結果本体
    result = QuizResult.query.get_or_404(result_id)

    # 自分の結果 or 管理者のみ閲覧可
    if result.user_id != current_user.id and getattr(current_user, "role", None) != "admin":
        abort(404)

    lesson = result.lesson
    course = lesson.course

    # この結果に紐づく詳細（1問ごとの解答）
    details = (
        QuizResultDetail.query
        .filter_by(result_id=result.id)
        .join(QuizResultDetail.question)
        .join(QuizResultDetail.choice)
        .all()
    )

    # 正答率（％）
    percent = 0
    if result.total_questions > 0:
        percent = int(result.score / result.total_questions * 100)

    return render_template(
        "quiz_result_detail.html",
        result=result,
        lesson=lesson,
        course=course,
        details=details,
        percent=percent,
    )

@bp.route("/quiz_retry/<int:result_id>")
@login_required
def quiz_retry(result_id: int):
    """不正解だけ再出題モード（問題表示）"""

    original = QuizResult.query.get_or_404(result_id)

    # 自分の結果以外は見れない
    if original.user_id != current_user.id:
        abort(404)

    # 不正解の問題だけ抽出
    wrong_details = [d for d in original.details if not d.is_correct]

    if not wrong_details:
        flash("不正解の問題はありません。全問正解です！", "info")
        return redirect(url_for("main.quiz_result_detail", result_id=result_id))

    # 出題する問題リスト
    questions = [d.question for d in wrong_details]

    return render_template(
        "quiz/quiz_retry.html",
        original=original,
        questions=questions,
    )


# ===========================
# クイズ受験（生徒用）
# ===========================
@bp.route("/lessons/<int:lesson_id>/quiz", methods=["GET", "POST"])
@login_required
def quiz_take(lesson_id: int):
    lesson = Lesson.query.get_or_404(lesson_id)
    course = lesson.course

    # 受講してない人はNG（管理者はOK）
    if current_user.role != "admin":
        enrollment = Enrollment.query.filter_by(
            user_id=current_user.id, course_id=course.id
        ).first()
        if not enrollment:
            flash("このコースを受講登録していません。", "danger")
            return redirect(url_for("main.course_detail", course_id=course.id))

    # このレッスンの全問題
    questions = (
        QuizQuestion.query.filter_by(lesson_id=lesson.id)
        .order_by(QuizQuestion.sort_order)
        .all()
    )

    if not questions:
        flash("このレッスンにはまだクイズがありません。", "info")
        return redirect(url_for("main.lesson_detail", lesson_id=lesson.id))

    # GET → クイズ画面表示
    if request.method == "GET":
        return render_template(
            "courses/quiz_take.html",
            lesson=lesson,
            questions=questions,
            result_detail={},  # 互換のため残しておく（今は未使用）
            score=None,
        )

    # POST → 採点 & QuizResult / QuizResultDetail 保存
    correct_count = 0

    # ① QuizResult を先に作る（score は後で更新）
    quiz_result = QuizResult(
        user_id=current_user.id,
        lesson_id=lesson.id,
        score=0,
        total_questions=len(questions),
        taken_at=datetime.utcnow(),
    )
    db.session.add(quiz_result)
    db.session.flush()  # quiz_result.id を取得する

    # ② 各問題について、選ばれた選択肢を QuizResultDetail に保存
    for q in questions:
        field_name = f"q_{q.id}"  # フォーム側の name="q_{{ question.id }}" に対応
        selected_choice_id = request.form.get(field_name)

        if not selected_choice_id:
            # 未回答ならスキップ（必要なら「未回答」用レコードを作るのも可）
            continue

        try:
            choice_id_int = int(selected_choice_id)
        except ValueError:
            continue

        choice = QuizChoice.query.get(choice_id_int)
        if not choice:
            continue

        is_correct = bool(choice.is_correct)
        if is_correct:
            correct_count += 1

        detail = QuizResultDetail(
            result_id=quiz_result.id,
            question_id=q.id,
            choice_id=choice.id,
            is_correct=is_correct,
        )
        db.session.add(detail)

    # ③ スコア更新 & コミット
    quiz_result.score = correct_count
    db.session.commit()

    flash(f"クイズ結果: {correct_count} / {len(questions)} 問正解でした。", "success")

    # ④ クイズ結果の詳細ページへリダイレクト
    return redirect(url_for("main.quiz_result_detail", result_id=quiz_result.id))

@bp.route("/quiz_retry/<int:result_id>", methods=["POST"])
@login_required
def quiz_retry_submit(result_id: int):
    """不正解だけ再挑戦の採点処理"""

    original = QuizResult.query.get_or_404(result_id)
    if original.user_id != current_user.id:
        abort(404)

    # 不正解の問題だけ
    wrong_details = [d for d in original.details if not d.is_correct]

    total = len(wrong_details)
    score = 0
    results = []

    for d in wrong_details:
        q = d.question
        field_name = f"q{q.id}"          # テンプレ側の name と対応
        selected_id = request.form.get(field_name)

        selected = None
        is_correct = False
        if selected_id:
            selected = QuizChoice.query.get(int(selected_id))
            if selected:
                is_correct = selected.is_correct

        if is_correct:
            score += 1

        # 正解選択肢
        correct_choice = next((c for c in q.choices if c.is_correct), None)

        results.append(
            {
                "question": q,
                "selected_text": selected.choice_text if selected else "未回答",
                "is_correct": is_correct,
                "correct_text": correct_choice.choice_text if correct_choice else None,
            }
        )

    return render_template(
        "quiz/quiz_retry_result.html",
        original=original,
        score=score,
        total=total,
        results=results,
    )


