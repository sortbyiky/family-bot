import logging

from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from db.database import get_session
from db.models import Parent, Member
from web.task_manager import task_manager

bp = Blueprint("family", __name__)
logger = logging.getLogger(__name__)

FAMILY_URLS = {
    "members": "https://myaccount.google.com/family/details",
    "invite": "https://myaccount.google.com/family/invite/send",
    "settings": "https://myaccount.google.com/family",
}


@bp.route("/")
def index():
    """家庭组入口 — 显示所有家长 + 快捷跳转链接"""
    with get_session() as session:
        parents = session.query(Parent).all()
        parent_list = []
        for p in parents:
            members = session.query(Member).filter_by(parent_id=p.id).all()
            parent_list.append({
                "id": p.id,
                "email": p.email,
                "nickname": p.nickname or "-",
                "has_creds": bool(p.password),
                "member_count": len(members),
                "members": [{"id": m.id, "email": m.email, "status": m.status} for m in members],
            })
    return render_template("family/index.html", parents=parent_list, urls=FAMILY_URLS)


@bp.route("/<int:parent_id>/members")
def parent_members(parent_id):
    """某个家长的家庭组管理页"""
    with get_session() as session:
        parent = session.get(Parent, parent_id)
        if not parent:
            flash("家长不存在", "danger")
            return redirect(url_for("family.index"))
        members = session.query(Member).filter_by(parent_id=parent_id).all()
        member_list = [{"id": m.id, "email": m.email, "status": m.status} for m in members]
        parent_data = {
            "id": parent.id,
            "email": parent.email,
            "nickname": parent.nickname or "-",
            "has_creds": bool(parent.password),
            "member_count": len(member_list),
            "members": member_list,
        }
    return render_template(
        "family/index.html",
        parents=[parent_data],
        urls=FAMILY_URLS,
        focus_parent=parent_data,
        focus_members=member_list,
    )


@bp.route("/open/<int:parent_id>/<page_type>", methods=["POST"])
def open_page(parent_id, page_type):
    """通过自动化打开家庭组页面（成员列表/邀请/设置）"""
    with get_session() as session:
        parent = session.get(Parent, parent_id)
        if not parent:
            flash("家长不存在", "danger")
            return redirect(url_for("family.index"))
        email = parent.email

    task_id = task_manager.run_family_open(parent_id, email, page_type)
    flash(f"正在打开家庭组{page_type}页面: {email}", "success")
    return redirect(request.referrer or url_for("family.index"))


@bp.route("/invite/<int:parent_id>", methods=["POST"])
def invite_member(parent_id):
    """自动邀请邮箱加入家庭组"""
    invite_email = request.form.get("invite_email", "").strip()
    if not invite_email:
        flash("请输入要邀请的邮箱", "warning")
        return redirect(request.referrer or url_for("family.index"))

    with get_session() as session:
        parent = session.get(Parent, parent_id)
        if not parent:
            flash("家长不存在", "danger")
            return redirect(url_for("family.index"))
        email = parent.email

    task_id = task_manager.run_family_invite(parent_id, email, invite_email)
    flash(f"正在邀请 {invite_email} 加入家庭组", "success")
    return redirect(request.referrer or url_for("family.index"))


@bp.route("/kick/<int:parent_id>", methods=["POST"])
def kick_member(parent_id):
    """自动踢出家庭组成员"""
    member_email = request.form.get("member_email", "").strip()
    if not member_email:
        flash("请指定要踢出的成员邮箱", "warning")
        return redirect(request.referrer or url_for("family.index"))

    with get_session() as session:
        parent = session.get(Parent, parent_id)
        if not parent:
            flash("家长不存在", "danger")
            return redirect(url_for("family.index"))
        email = parent.email

    task_id = task_manager.run_family_kick(parent_id, email, member_email)
    flash(f"正在踢出成员 {member_email}", "success")
    return redirect(request.referrer or url_for("family.index"))
