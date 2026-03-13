import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from config import MAX_CONCURRENT_TASKS

logger = logging.getLogger(__name__)

MAX_FINISHED_TASKS = 100


class TaskManager:
    """后台任务管理器，线程池执行自动化任务"""

    _instance = None
    _init_lock = threading.Lock()

    def __new__(cls):
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._tasks = {}
                cls._instance._lock = threading.Lock()
                cls._instance._counter = 0
                cls._instance._pool = ThreadPoolExecutor(
                    max_workers=MAX_CONCURRENT_TASKS,
                    thread_name_prefix="task",
                )
            return cls._instance

    def _gen_id(self):
        with self._lock:
            self._counter += 1
            return f"task_{int(time.time() * 1000)}_{self._counter}"

    def _cleanup_finished(self):
        """清理已完成的旧任务，保留最近 MAX_FINISHED_TASKS 个（调用方须持锁）"""
        finished = [
            (tid, t) for tid, t in self._tasks.items()
            if t["status"] in ("done", "failed")
        ]
        if len(finished) <= MAX_FINISHED_TASKS:
            return
        finished.sort(key=lambda x: x[1].get("finished_at", ""))
        for tid, _ in finished[:-MAX_FINISHED_TASKS]:
            del self._tasks[tid]

    def _notify_telegram(self, message: str):
        """发送 Telegram 通知"""
        import urllib.request
        import json
        try:
            token = "8793608547:AAFVGk0HCJCIboSJpJGyykR47g5cWR_O3lY"
            chat_id = "8375509339"
            payload = json.dumps({"chat_id": chat_id, "text": message}).encode()
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            logger.warning("Telegram 通知发送失败: %s", e)

    def _finish_task(self, task_id, status, error=None):
        """统一结束任务的状态更新"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task["status"] = status
                task["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if error:
                    task["error"] = str(error)
                self._cleanup_finished()

        # 失败时发 Telegram 通知
        if status == "failed" and task:
            email = task.get("email", "unknown")
            task_type = task.get("type", "unknown")
            err_msg = str(error) if error else "未知错误"
            self._notify_telegram(
                f"❌ family-bot 任务失败\n\n"
                f"账号: {email}\n"
                f"类型: {task_type}\n"
                f"错误: {err_msg}\n"
                f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

    def get_all_tasks(self):
        with self._lock:
            return dict(self._tasks)

    def clear_finished_tasks(self):
        """清理所有已完成/失败的任务"""
        with self._lock:
            to_del = [tid for tid, t in self._tasks.items() if t["status"] in ("done", "failed")]
            for tid in to_del:
                del self._tasks[tid]
            return len(to_del)

    def _create_task(self, task_type, member_id, email, **extra):
        task_id = self._gen_id()
        with self._lock:
            self._tasks[task_id] = {
                "type": task_type,
                "member_id": member_id,
                "email": email,
                "status": "running",
                "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "finished_at": None,
                "error": None,
                **extra,
            }
        return task_id

    def run_member(self, member_id: int, email: str):
        """执行单个成员"""
        task_id = self._create_task("member", member_id, email)
        self._pool.submit(self._exec, task_id, [member_id])
        return task_id

    def run_parent(self, parent_id: int, parent_email: str):
        """执行某家长下所有待处理成员（每个成员独立任务并行执行）"""
        from db.database import get_session
        from db.models import Member

        with get_session() as session:
            members = session.query(Member).filter(
                Member.parent_id == parent_id,
                Member.status.in_(["pending", "gemini_done"])
            ).all()
            member_info = [(m.id, m.email) for m in members]

        if not member_info:
            return []

        return [self.run_member(mid, email) for mid, email in member_info]

    def run_all(self):
        """执行所有待处理成员（每个成员独立任务并行执行）"""
        from db.database import get_session
        from db.models import Member

        with get_session() as session:
            members = session.query(Member).filter(
                Member.status.in_(["pending", "gemini_done"])
            ).all()
            member_info = [(m.id, m.email) for m in members]

        if not member_info:
            return []

        return [self.run_member(mid, email) for mid, email in member_info]

    def run_open_browser(self, member_id: int, email: str):
        """打开成员浏览器并自动登录"""
        task_id = self._create_task("open_browser", member_id, email)
        self._pool.submit(self._exec_open_browser, task_id, member_id)
        return task_id

    def _exec_open_browser(self, task_id: str, member_id: int):
        from automation.open_browser import open_browser_for_member
        try:
            asyncio.run(open_browser_for_member(member_id))
            self._finish_task(task_id, "done")
        except Exception as e:
            logger.exception("打开浏览器失败: member_id=%s", member_id)
            self._finish_task(task_id, "failed", error=e)

    def run_open_browser_parent(self, parent_id: int, email: str):
        """打开家长浏览器并自动登录（用于首次手动登录存 cookie）"""
        task_id = self._create_task("open_browser_parent", parent_id, email)
        self._pool.submit(self._exec_open_browser_parent, task_id, parent_id)
        return task_id

    def _exec_open_browser_parent(self, task_id: str, parent_id: int):
        from automation.open_browser import open_browser_for_parent
        try:
            asyncio.run(open_browser_for_parent(parent_id))
            self._finish_task(task_id, "done")
        except Exception as e:
            logger.exception("打开家长浏览器失败: parent_id=%s", parent_id)
            self._finish_task(task_id, "failed", error=e)

    def run_antigravity(self, member_id: int, email: str, oauth_url: str):
        """执行 Antigravity OAuth 登录"""
        task_id = self._create_task("antigravity", member_id, email, oauth_url=oauth_url)
        self._pool.submit(self._exec_antigravity, task_id, member_id, oauth_url)
        return task_id

    def _exec_antigravity(self, task_id: str, member_id: int, oauth_url: str):
        """线程内执行 Antigravity 登录"""
        from automation.antigravity_login import antigravity_login

        try:
            result = asyncio.run(antigravity_login(member_id, oauth_url))
            if result:
                self._finish_task(task_id, "done")
            else:
                self._finish_task(task_id, "failed", error="Antigravity 登录未成功")
        except Exception as e:
            logger.exception("Antigravity 登录失败: member_id=%s", member_id)
            self._finish_task(task_id, "failed", error=e)

    def run_appeal(self, member_id: int, email: str):
        """打开成员浏览器并访问申诉表单"""
        task_id = self._create_task("appeal", member_id, email)
        self._pool.submit(self._exec_appeal, task_id, member_id)
        return task_id

    def _exec_appeal(self, task_id: str, member_id: int):
        from automation.appeal_form import open_appeal_form
        try:
            asyncio.run(open_appeal_form(member_id))
            self._finish_task(task_id, "done")
        except Exception as e:
            logger.exception("认罪表单失败: member_id=%s", member_id)
            self._finish_task(task_id, "failed", error=e)

    def _exec(self, task_id: str, member_ids: list):
        """在线程内逐个执行成员流程"""
        from cli.auto_cmd import run_member_flow

        try:
            for i, mid in enumerate(member_ids):
                logger.info("_exec 开始执行成员: member_id=%s, task_id=%s", mid, task_id)
                asyncio.run(run_member_flow(mid))
                logger.info("_exec 成员执行完成: member_id=%s", mid)
                with self._lock:
                    self._tasks[task_id]["progress"] = i + 1
            self._finish_task(task_id, "done")
        except Exception as e:
            logger.exception("成员流程执行失败: task_id=%s", task_id)
            self._finish_task(task_id, "failed", error=e)

    # ───────────────── 家庭组管理任务 ─────────────────

    def _create_parent_task(self, task_type, parent_id, email, **extra):
        """创建家长相关任务"""
        task_id = self._gen_id()
        with self._lock:
            self._tasks[task_id] = {
                "type": task_type,
                "parent_id": parent_id,
                "email": email,
                "status": "running",
                "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "finished_at": None,
                "error": None,
                "result": None,
                **extra,
            }
        return task_id

    def _finish_parent_task(self, task_id, status, result=None, error=None):
        """结束家长任务并存储结果"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task["status"] = status
                task["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if result is not None:
                    task["result"] = result
                if error:
                    task["error"] = str(error)
                self._cleanup_finished()

    def run_family_list(self, parent_id: int, email: str) -> str:
        """列出家庭组成员"""
        task_id = self._create_parent_task("family_list", parent_id, email)
        self._pool.submit(self._exec_family_list, task_id, parent_id)
        return task_id

    def _exec_family_list(self, task_id: str, parent_id: int):
        from automation.family_manage import list_family_members
        from automation.browser import launch_parent_context
        from automation.google_login import google_login
        from db.database import get_session
        from db.models import Parent
        from utils.crypto import decrypt_safe

        try:
            with get_session() as session:
                parent = session.get(Parent, parent_id)
                if not parent:
                    self._finish_parent_task(task_id, "failed", error="家长不存在")
                    return
                email = parent.email
                password = decrypt_safe(parent.password) if parent.password else ""
                totp = decrypt_safe(parent.totp_secret) if parent.totp_secret else ""

            if not password:
                self._finish_parent_task(task_id, "failed", error="家长未设置密码，请先在家长管理页面编辑凭据")
                return

            async def _run():
                from playwright.async_api import async_playwright
                async with async_playwright() as p:
                    context, page = await launch_parent_context(p, parent_id)
                    try:
                        login_ok = await google_login(page, email, password, totp)
                        if not login_ok:
                            return None, "Google 登录失败"
                        members = await list_family_members(page)
                        return members, None
                    finally:
                        await context.close()

            members, err = asyncio.run(_run())
            if err:
                self._finish_parent_task(task_id, "failed", error=err)
            else:
                self._finish_parent_task(task_id, "done", result=members)
        except Exception as e:
            logger.exception("列出家庭组成员失败: parent_id=%s", parent_id)
            self._finish_parent_task(task_id, "failed", error=e)

    def run_family_kick(self, parent_id: int, email: str, target: str) -> str:
        """踢出家庭组成员"""
        task_id = self._create_parent_task("family_kick", parent_id, email, target=target)
        self._pool.submit(self._exec_family_kick, task_id, parent_id, target)
        return task_id

    def _exec_family_kick(self, task_id: str, parent_id: int, target: str):
        from automation.family_manage import kick_family_member
        from automation.browser import launch_parent_context
        from automation.google_login import google_login
        from db.database import get_session
        from db.models import Parent
        from utils.crypto import decrypt_safe

        try:
            with get_session() as session:
                parent = session.get(Parent, parent_id)
                if not parent:
                    self._finish_parent_task(task_id, "failed", error="家长不存在")
                    return
                email = parent.email
                password = decrypt_safe(parent.password) if parent.password else ""
                totp = decrypt_safe(parent.totp_secret) if parent.totp_secret else ""

            if not password:
                self._finish_parent_task(task_id, "failed", error="家长未设置密码")
                return

            async def _run():
                from playwright.async_api import async_playwright
                async with async_playwright() as p:
                    context, page = await launch_parent_context(p, parent_id)
                    try:
                        login_ok = await google_login(page, email, password, totp)
                        if not login_ok:
                            return False, "Google 登录失败"
                        ok = await kick_family_member(page, target)
                        return ok, None if ok else "踢出操作未成功"
                    finally:
                        await context.close()

            ok, err = asyncio.run(_run())
            if err:
                self._finish_parent_task(task_id, "failed", error=err)
            else:
                self._finish_parent_task(task_id, "done", result={"success": ok})
        except Exception as e:
            logger.exception("踢出成员失败: parent_id=%s target=%s", parent_id, target)
            self._finish_parent_task(task_id, "failed", error=e)

    def run_family_invite(self, parent_id: int, email: str, target_email: str) -> str:
        """邀请新成员"""
        task_id = self._create_parent_task("family_invite", parent_id, email, target=target_email)
        self._pool.submit(self._exec_family_invite, task_id, parent_id, target_email)
        return task_id

    def _exec_family_invite(self, task_id: str, parent_id: int, target_email: str):
        from automation.family_manage import invite_family_member
        from automation.browser import launch_parent_context
        from automation.google_login import google_login
        from db.database import get_session
        from db.models import Parent
        from utils.crypto import decrypt_safe

        try:
            with get_session() as session:
                parent = session.get(Parent, parent_id)
                if not parent:
                    self._finish_parent_task(task_id, "failed", error="家长不存在")
                    return
                email = parent.email
                password = decrypt_safe(parent.password) if parent.password else ""
                totp = decrypt_safe(parent.totp_secret) if parent.totp_secret else ""

            if not password:
                self._finish_parent_task(task_id, "failed", error="家长未设置密码")
                return

            async def _run():
                from playwright.async_api import async_playwright
                async with async_playwright() as p:
                    context, page = await launch_parent_context(p, parent_id)
                    try:
                        login_ok = await google_login(page, email, password, totp)
                        if not login_ok:
                            return False, "Google 登录失败"
                        ok = await invite_family_member(page, target_email)
                        return ok, None if ok else "邀请操作未成功"
                    finally:
                        await context.close()

            ok, err = asyncio.run(_run())
            if err:
                self._finish_parent_task(task_id, "failed", error=err)
            else:
                self._finish_parent_task(task_id, "done", result={"success": ok})
        except Exception as e:
            logger.exception("邀请成员失败: parent_id=%s target=%s", parent_id, target_email)
            self._finish_parent_task(task_id, "failed", error=e)

    def run_family_cancel_invite(self, parent_id: int, email: str, target: str) -> str:
        """取消未接受的邀请"""
        task_id = self._create_parent_task("family_cancel_invite", parent_id, email, target=target)
        self._pool.submit(self._exec_family_cancel_invite, task_id, parent_id, target)
        return task_id

    def _exec_family_cancel_invite(self, task_id: str, parent_id: int, target: str):
        from automation.family_manage import cancel_family_invite
        from automation.browser import launch_parent_context
        from automation.google_login import google_login
        from db.database import get_session
        from db.models import Parent
        from utils.crypto import decrypt_safe

        try:
            with get_session() as session:
                parent = session.get(Parent, parent_id)
                if not parent:
                    self._finish_parent_task(task_id, "failed", error="家长不存在")
                    return
                email = parent.email
                password = decrypt_safe(parent.password) if parent.password else ""
                totp = decrypt_safe(parent.totp_secret) if parent.totp_secret else ""

            if not password:
                self._finish_parent_task(task_id, "failed", error="家长未设置密码")
                return

            async def _run():
                from playwright.async_api import async_playwright
                async with async_playwright() as p:
                    context, page = await launch_parent_context(p, parent_id)
                    try:
                        login_ok = await google_login(page, email, password, totp)
                        if not login_ok:
                            return False, "Google 登录失败"
                        ok = await cancel_family_invite(page, target)
                        return ok, None if ok else "取消邀请操作未成功"
                    finally:
                        await context.close()

            ok, err = asyncio.run(_run())
            if err:
                self._finish_parent_task(task_id, "failed", error=err)
            else:
                self._finish_parent_task(task_id, "done", result={"success": ok})
        except Exception as e:
            logger.exception("取消邀请失败: parent_id=%s target=%s", parent_id, target)
            self._finish_parent_task(task_id, "failed", error=e)

    def get_task_result(self, task_id: str) -> dict:
        """获取任务详情（含 result）"""
        with self._lock:
            return dict(self._tasks.get(task_id, {}))


task_manager = TaskManager()
