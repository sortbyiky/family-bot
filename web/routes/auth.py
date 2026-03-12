import config as _config
from flask import Blueprint, render_template, request, redirect, url_for, session, flash

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("authenticated"):
        return redirect(url_for("dashboard.index"))

    error = None
    if request.method == "POST":
        pwd = request.form.get("password", "").strip()
        if pwd == _config.WEB_AUTH_PASSWORD:
            session["authenticated"] = True
            session.permanent = True
            next_url = request.args.get("next") or url_for("dashboard.index")
            return redirect(next_url)
        else:
            error = "密码错误，请重试"

    return render_template("auth/login.html", error=error)


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/change-password", methods=["GET", "POST"])
def change_password():
    if not session.get("authenticated"):
        return redirect(url_for("auth.login"))

    error = None
    success = None

    if request.method == "POST":
        current = request.form.get("current_password", "").strip()
        new_pwd = request.form.get("new_password", "").strip()
        confirm = request.form.get("confirm_password", "").strip()

        if current != _config.WEB_AUTH_PASSWORD:
            error = "当前密码错误"
        elif len(new_pwd) < 4:
            error = "新密码至少 4 位"
        elif new_pwd != confirm:
            error = "两次输入不一致"
        else:
            _config.save_password(new_pwd)
            success = "密码已修改，请重新登录"
            session.clear()
            return render_template("auth/change_password.html", success=success)

    return render_template("auth/change_password.html", error=error)
