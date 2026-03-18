import json
import logging
import os

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify

from config import DATA_DIR
from web.task_manager import task_manager

bp = Blueprint("age_verify", __name__)
logger = logging.getLogger(__name__)

CARDS_FILE = os.path.join(DATA_DIR, "age_verify_cards.json")


def _load_cards() -> list:
    if not os.path.exists(CARDS_FILE):
        return []
    try:
        with open(CARDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_cards(cards: list):
    with open(CARDS_FILE, "w", encoding="utf-8") as f:
        json.dump(cards, f, ensure_ascii=False, indent=2)


@bp.route("/")
def index():
    from db.database import get_session
    from db.models import Member
    from sqlalchemy.orm import joinedload

    cards = _load_cards()
    with get_session() as session:
        members = session.query(Member).options(joinedload(Member.parent)).all()
        member_list = [{
            "id": m.id,
            "email": m.email,
            "parent_email": m.parent.email if m.parent else "-",
            "status": m.status,
        } for m in members]

    tasks = task_manager.get_all_tasks()
    age_tasks = {k: v for k, v in tasks.items() if v.get("type") == "age_verify"}

    return render_template(
        "age_verify/list.html",
        cards=cards,
        members=member_list,
        age_tasks=age_tasks,
    )


@bp.route("/card/add", methods=["POST"])
def add_card():
    name = request.form.get("name", "").strip()
    card_number = request.form.get("card_number", "").strip().replace(" ", "")
    cvv = request.form.get("cvv", "").strip()
    expiry = request.form.get("expiry", "").strip()
    zip_code = request.form.get("zip_code", "").strip()
    country = request.form.get("country", "US").strip()

    if not all([name, card_number, cvv, expiry]):
        flash("持卡人、卡号、CVV、过期时间为必填项", "danger")
        return redirect(url_for("age_verify.index"))

    cards = _load_cards()
    cards.append({
        "name": name,
        "card_number": card_number,
        "cvv": cvv,
        "expiry": expiry,
        "zip_code": zip_code,
        "country": country,
    })
    _save_cards(cards)
    flash(f"卡片 ****{card_number[-4:]} ({name}) 已添加", "success")
    return redirect(url_for("age_verify.index"))


@bp.route("/card/import", methods=["POST"])
def import_cards():
    raw = request.form.get("cards_data", "").strip()
    if not raw:
        flash("请填写卡片数据", "danger")
        return redirect(url_for("age_verify.index"))

    cards = _load_cards()
    added = 0
    errors = 0

    for line_num, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if "----" in line:
            parts = [p.strip() for p in line.split("----")]
        else:
            parts = [p.strip() for p in line.split("|")]

        if len(parts) < 4:
            flash(f"第 {line_num} 行格式错误（至少需要: 姓名|卡号|CVV|过期时间）", "warning")
            errors += 1
            continue

        card = {
            "name": parts[0],
            "card_number": parts[1].replace(" ", ""),
            "cvv": parts[2],
            "expiry": parts[3],
            "zip_code": parts[4] if len(parts) > 4 else "",
            "country": parts[5] if len(parts) > 5 else "US",
        }
        cards.append(card)
        added += 1

    _save_cards(cards)
    msg = f"导入完成：成功 {added} 张"
    if errors:
        msg += f"，失败 {errors} 张"
    flash(msg, "success" if errors == 0 else "warning")
    return redirect(url_for("age_verify.index"))


@bp.route("/card/delete/<int:card_idx>", methods=["POST"])
def delete_card(card_idx):
    cards = _load_cards()
    if 0 <= card_idx < len(cards):
        removed = cards.pop(card_idx)
        _save_cards(cards)
        flash(f"卡片 ****{removed['card_number'][-4:]} 已删除", "success")
    else:
        flash("卡片索引无效", "danger")
    return redirect(url_for("age_verify.index"))


@bp.route("/card/clear", methods=["POST"])
def clear_cards():
    _save_cards([])
    flash("所有卡片已清空", "success")
    return redirect(url_for("age_verify.index"))


@bp.route("/run/<int:member_id>", methods=["POST"])
def run_verify(member_id):
    from db.database import get_session
    from db.models import Member

    with get_session() as session:
        member = session.get(Member, member_id)
        if not member:
            flash("成员不存在", "danger")
            return redirect(url_for("age_verify.index"))
        task_id = task_manager.run_age_verify(member.id, member.email)
        flash(f"年龄认证浏览器已启动: {member.email}，请在弹出的浏览器中手动填写卡片信息", "info")

    return redirect(url_for("age_verify.index"))


@bp.route("/status")
def status():
    tasks = task_manager.get_all_tasks()
    age_tasks = {k: v for k, v in tasks.items() if v.get("type") == "age_verify"}
    return jsonify(age_tasks)
