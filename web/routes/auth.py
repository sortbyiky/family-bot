from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from config import WEB_AUTH_PASSWORD

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("authenticated"):
        return redirect(url_for("dashboard.index"))

    error = None
    if request.method == "POST":
        pwd = request.form.get("password", "").strip()
        if pwd == WEB_AUTH_PASSWORD:
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
