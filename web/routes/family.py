import logging

from flask import Blueprint, render_template, redirect, url_for
from db.database import get_session
from db.models import Parent

bp = Blueprint("family", __name__)
logger = logging.getLogger(__name__)

# Google 家庭组相关页面
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
            parent_list.append({
                "id": p.id,
                "email": p.email,
                "nickname": p.nickname or "-",
                "has_creds": bool(p.password),
            })
    return render_template("family/index.html", parents=parent_list, urls=FAMILY_URLS)
