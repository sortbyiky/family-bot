import logging

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from sqlalchemy import func
from db.database import get_session
from db.models import Parent, Member
from utils.crypto import encrypt, decrypt_safe

bp = Blueprint("parent", __name__)
logger = logging.getLogger(__name__)


@bp.route("/")
def list_parents():
    with get_session() as session:
        # 子查询统计成员数，避免 N+1
        member_count_sq = (
            session.query(Member.parent_id, func.count(Member.id).label("cnt"))
            .group_by(Member.parent_id)
            .subquery()
        )
        rows = (
            session.query(Parent, func.coalesce(member_count_sq.c.cnt, 0).label("member_count"))
            .outerjoin(member_count_sq, Parent.id == member_count_sq.c.parent_id)
            .all()
        )

        data = []
        for p, member_count in rows:
            data.append({
                "id": p.id,
                "email": p.email,
                "nickname": p.nickname or "-",
                "max_members": p.max_members,
                "member_count": member_count,
                "has_creds": bool(p.password),
                "created_at": p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else "-",
            })
        return render_template("parent/list.html", parents=data)


@bp.route("/add", methods=["POST"])
def add_parent():
    email = request.form.get("email", "").strip()
    nickname = request.form.get("nickname", "").strip()
    max_members = request.form.get("max_members", "5").strip()

    if not email:
        flash("邮箱不能为空", "danger")
        return redirect(url_for("parent.list_parents"))

    try:
        max_members_int = int(max_members) if max_members else 5
    except ValueError:
        flash("最大成员数必须为数字", "danger")
        return redirect(url_for("parent.list_parents"))

    password = request.form.get("password", "").strip()
    totp_secret = request.form.get("totp_secret", "").strip()

    with get_session() as session:
        exists = session.query(Parent).filter_by(email=email).first()
        if exists:
            flash(f"家长 {email} 已存在", "warning")
            return redirect(url_for("parent.list_parents"))

        p = Parent(
            email=email,
            nickname=nickname or None,
            max_members=max_members_int,
            password=encrypt(password) if password else None,
            totp_secret=encrypt(totp_secret) if totp_secret else None,
        )
        session.add(p)
        session.commit()
        flash(f"家长 {email} 添加成功", "success")
    return redirect(url_for("parent.list_parents"))


@bp.route("/edit/<int:parent_id>", methods=["POST"])
def edit_parent(parent_id):
    """编辑家长凭据（密码、2FA）"""
    password = request.form.get("password", "").strip()
    totp_secret = request.form.get("totp_secret", "").strip()
    nickname = request.form.get("nickname", "").strip()

    with get_session() as session:
        p = session.get(Parent, parent_id)
        if not p:
            flash("家长不存在", "danger")
            return redirect(url_for("parent.list_parents"))

        if nickname is not None:
            p.nickname = nickname or None
        if password:
            p.password = encrypt(password)
        if totp_secret:
            p.totp_secret = encrypt(totp_secret)
        session.commit()
        flash(f"家长 {p.email} 凭据已更新", "success")
    return redirect(url_for("parent.list_parents"))


@bp.route("/secret/<int:parent_id>")
def get_secret(parent_id):
    """按需返回家长的解密密码和 TOTP 密钥"""
    with get_session() as session:
        p = session.get(Parent, parent_id)
        if not p:
            return jsonify({"error": "家长不存在"}), 404
        return jsonify({
            "password": decrypt_safe(p.password) if p.password else "",
            "totp_secret": decrypt_safe(p.totp_secret) if p.totp_secret else "",
        })


@bp.route("/delete/<int:parent_id>", methods=["POST"])
def delete_parent(parent_id):
    with get_session() as session:
        p = session.get(Parent, parent_id)
        if not p:
            flash("家长不存在", "danger")
        else:
            email = p.email
            session.delete(p)
            session.commit()
            flash(f"家长 {email} 已删除", "success")
    return redirect(url_for("parent.list_parents"))
