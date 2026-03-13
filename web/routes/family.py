import logging

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from db.database import get_session
from db.models import Parent
from web.task_manager import task_manager

bp = Blueprint("family", __name__)
logger = logging.getLogger(__name__)


@bp.route("/")
def index():
    """家庭组入口 — 显示所有家长"""
    with get_session() as session:
        parents = session.query(Parent).all()
        parent_list = []
        for p in parents:
            has_creds = bool(p.password)
            parent_list.append({
                "id": p.id,
                "email": p.email,
                "nickname": p.nickname or "-",
                "has_creds": has_creds,
            })
    return render_template("family/index.html", parents=parent_list)


@bp.route("/<int:parent_id>/members")
def manage(parent_id):
    """家庭组管理页面"""
    with get_session() as session:
        parent = session.get(Parent, parent_id)
        if not parent:
            flash("家长不存在", "danger")
            return redirect(url_for("family.index"))
        parent_data = {
            "id": parent.id,
            "email": parent.email,
            "nickname": parent.nickname or "-",
            "has_creds": bool(parent.password),
        }
    return render_template("family/manage.html", parent=parent_data)


@bp.route("/<int:parent_id>/list_members", methods=["POST"])
def list_members(parent_id):
    """启动-列出成员异步任务"""
    with get_session() as session:
        parent = session.get(Parent, parent_id)
        if not parent:
            return jsonify({"error": "家长不存在"}), 404
        if not parent.password:
            return jsonify({"error": "家长未设置密码，请先在家长管理页面编辑凭据"}), 400
        task_id = task_manager.run_family_list(parent_id, parent.email)
    return jsonify({"task_id": task_id})


@bp.route("/<int:parent_id>/kick", methods=["POST"])
def kick_member(parent_id):
    """启动-踢出成员异步任务"""
    target = request.json.get("target", "").strip() if request.is_json else request.form.get("target", "").strip()
    if not target:
        return jsonify({"error": "请填写成员邮箱或名称"}), 400

    with get_session() as session:
        parent = session.get(Parent, parent_id)
        if not parent:
            return jsonify({"error": "家长不存在"}), 404
        if not parent.password:
            return jsonify({"error": "家长未设置密码"}), 400
        task_id = task_manager.run_family_kick(parent_id, parent.email, target)
    return jsonify({"task_id": task_id})


@bp.route("/<int:parent_id>/invite", methods=["POST"])
def invite_member(parent_id):
    """启动-邀请成员异步任务"""
    target_email = request.json.get("email", "").strip() if request.is_json else request.form.get("email", "").strip()
    if not target_email:
        return jsonify({"error": "请填写邀请邮箱"}), 400

    with get_session() as session:
        parent = session.get(Parent, parent_id)
        if not parent:
            return jsonify({"error": "家长不存在"}), 404
        if not parent.password:
            return jsonify({"error": "家长未设置密码"}), 400
        task_id = task_manager.run_family_invite(parent_id, parent.email, target_email)
    return jsonify({"task_id": task_id})


@bp.route("/<int:parent_id>/cancel_invite", methods=["POST"])
def cancel_invite(parent_id):
    """启动-取消邀请异步任务"""
    target = request.json.get("target", "").strip() if request.is_json else request.form.get("target", "").strip()
    if not target:
        return jsonify({"error": "请填写成员邮箱或名称"}), 400

    with get_session() as session:
        parent = session.get(Parent, parent_id)
        if not parent:
            return jsonify({"error": "家长不存在"}), 404
        if not parent.password:
            return jsonify({"error": "家长未设置密码"}), 400
        task_id = task_manager.run_family_cancel_invite(parent_id, parent.email, target)
    return jsonify({"task_id": task_id})


@bp.route("/task/<task_id>")
def task_result(task_id):
    """获取任务结果（轮询接口）"""
    task = task_manager.get_task_result(task_id)
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify(task)
