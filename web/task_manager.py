import asyncio
import logging
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future
from datetime import datetime

from config import MAX_CONCURRENT_TASKS

logger = logging.getLogger(__name__)

MAX_FINISHED_TASKS = 100
DEFAULT_TASK_TIMEOUT = 300


class TaskManager:
    """后台任务管理器，线程池执行自动化任务，支持取消和超时"""

    _instance = None
    _init_lock = threading.Lock()

    def __new__(cls):
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._tasks = {}
                cls._instance._lock = threading.Lock()
                cls._instance._counter = 0
                cls._instance._futures = {}
                cls._instance._cancel_events = {}
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
        finished = [
            (tid, t) for tid, t in self._tasks.items()
            if t["status"] in ("done", "failed", "cancelled")
        ]
        if len(finished) <= MAX_FINISHED_TASKS:
            return
        finished.sort(key=lambda x: x[1].get("finished_at", ""))
        for tid, _ in finished[:-MAX_FINISHED_TASKS]:
            del self._tasks[tid]
            self._futures.pop(tid, None)
            self._cancel_events.pop(tid, None)

    def _notify_telegram(self, message: str):
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
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                if task["status"] == "cancelled":
                    return
                task["status"] = status
                task["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if error:
                    task["error"] = str(error)[:500]
                self._cleanup_finished()

        if status == "failed" and task:
            email = task.get("email", "unknown")
            task_type = task.get("type", "unknown")
            err_msg = str(error)[:200] if error else "未知错误"
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
        with self._lock:
            to_del = [tid for tid, t in self._tasks.items() if t["status"] in ("done", "failed", "cancelled")]
            for tid in to_del:
                del self._tasks[tid]
                self._futures.pop(tid, None)
                self._cancel_events.pop(tid, None)
            return len(to_del)

    def cancel_task(self, task_id: str) -> bool:
        """取消正在运行的任务"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task["status"] != "running":
                return False
            task["status"] = "cancelled"
            task["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            task["error"] = "用户手动取消"

        cancel_event = self._cancel_events.get(task_id)
        if cancel_event:
            cancel_event.set()

        future = self._futures.get(task_id)
        if future and not future.done():
            future.cancel()

        self._kill_task_browser(task_id)
        logger.info("任务已取消: %s", task_id)
        return True

    def cancel_all_running(self) -> int:
        """取消所有运行中的任务"""
        with self._lock:
            running = [tid for tid, t in self._tasks.items() if t["status"] == "running"]
        count = 0
        for tid in running:
            if self.cancel_task(tid):
                count += 1
        return count

    def _kill_task_browser(self, task_id: str):
        """尝试杀掉任务关联的浏览器进程"""
        import subprocess
        try:
            result = subprocess.run(
                ["pgrep", "-f", "Google Chrome for Testing"],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip():
                for pid_str in result.stdout.strip().split("\n"):
                    pid = int(pid_str.strip())
                    try:
                        os.kill(pid, signal.SIGTERM)
                        logger.info("已终止浏览器进程: pid=%s (task=%s)", pid, task_id)
                    except (ProcessLookupError, PermissionError):
                        pass
        except Exception:
            pass

    def _create_task(self, task_type, member_id, email, **extra):
        task_id = self._gen_id()
        cancel_event = threading.Event()
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
            self._cancel_events[task_id] = cancel_event
        return task_id, cancel_event

    def _is_cancelled(self, task_id: str) -> bool:
        event = self._cancel_events.get(task_id)
        return event.is_set() if event else False

    # ──────────── 成员全流程 ────────────

    def run_member(self, member_id: int, email: str):
        task_id, cancel_event = self._create_task("member", member_id, email)
        future = self._pool.submit(self._exec, task_id, [member_id])
        self._futures[task_id] = future
        return task_id

    def run_parent(self, parent_id: int, parent_email: str):
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

    # ──────────── 打开浏览器 ────────────

    def run_open_browser(self, member_id: int, email: str):
        task_id, _ = self._create_task("open_browser", member_id, email)
        future = self._pool.submit(self._exec_open_browser, task_id, member_id)
        self._futures[task_id] = future
        return task_id

    def _exec_open_browser(self, task_id: str, member_id: int):
        from automation.open_browser import open_browser_for_member
        try:
            if self._is_cancelled(task_id):
                return
            asyncio.run(open_browser_for_member(member_id))
            self._finish_task(task_id, "done")
        except Exception as e:
            if not self._is_cancelled(task_id):
                logger.exception("打开浏览器失败: member_id=%s", member_id)
                self._finish_task(task_id, "failed", error=e)

    def run_open_browser_parent(self, parent_id: int, email: str):
        task_id, _ = self._create_task("open_browser_parent", parent_id, email)
        future = self._pool.submit(self._exec_open_browser_parent, task_id, parent_id)
        self._futures[task_id] = future
        return task_id

    def _exec_open_browser_parent(self, task_id: str, parent_id: int):
        from automation.open_browser import open_browser_for_parent
        try:
            if self._is_cancelled(task_id):
                return
            asyncio.run(open_browser_for_parent(parent_id))
            self._finish_task(task_id, "done")
        except Exception as e:
            if not self._is_cancelled(task_id):
                logger.exception("打开家长浏览器失败: parent_id=%s", parent_id)
                self._finish_task(task_id, "failed", error=e)

    # ──────────── Antigravity OAuth ────────────

    def run_antigravity(self, member_id: int, email: str, oauth_url: str):
        task_id, _ = self._create_task("antigravity", member_id, email, oauth_url=oauth_url)
        future = self._pool.submit(self._exec_antigravity, task_id, member_id, oauth_url)
        self._futures[task_id] = future
        return task_id

    def _exec_antigravity(self, task_id: str, member_id: int, oauth_url: str):
        from automation.antigravity_login import antigravity_login
        try:
            if self._is_cancelled(task_id):
                return
            result = asyncio.run(antigravity_login(member_id, oauth_url))
            if result:
                self._finish_task(task_id, "done")
            else:
                self._finish_task(task_id, "failed", error="Antigravity 登录未成功")
        except Exception as e:
            if not self._is_cancelled(task_id):
                logger.exception("Antigravity 登录失败: member_id=%s", member_id)
                self._finish_task(task_id, "failed", error=e)

    # ──────────── 申诉表单 ────────────

    def run_appeal(self, member_id: int, email: str):
        task_id, _ = self._create_task("appeal", member_id, email)
        future = self._pool.submit(self._exec_appeal, task_id, member_id)
        self._futures[task_id] = future
        return task_id

    def _exec_appeal(self, task_id: str, member_id: int):
        from automation.appeal_form import open_appeal_form
        try:
            if self._is_cancelled(task_id):
                return
            asyncio.run(open_appeal_form(member_id))
            self._finish_task(task_id, "done")
        except Exception as e:
            if not self._is_cancelled(task_id):
                logger.exception("认罪表单失败: member_id=%s", member_id)
                self._finish_task(task_id, "failed", error=e)

    # ──────────── 家庭组管理 ────────────

    def run_family_open(self, parent_id: int, email: str, page_type: str):
        task_id, _ = self._create_task("family_open", parent_id, email, page_type=page_type)
        future = self._pool.submit(self._exec_family_open, task_id, parent_id, page_type)
        self._futures[task_id] = future
        return task_id

    def _exec_family_open(self, task_id: str, parent_id: int, page_type: str):
        from automation.family_manage import open_family_page
        try:
            if self._is_cancelled(task_id):
                return
            asyncio.run(open_family_page(parent_id, page_type))
            self._finish_task(task_id, "done")
        except Exception as e:
            if not self._is_cancelled(task_id):
                logger.exception("打开家庭组页面失败: parent_id=%s, type=%s", parent_id, page_type)
                self._finish_task(task_id, "failed", error=e)

    def run_family_invite(self, parent_id: int, email: str, invite_email: str):
        task_id, _ = self._create_task("family_invite", parent_id, email, invite_email=invite_email)
        future = self._pool.submit(self._exec_family_invite, task_id, parent_id, invite_email)
        self._futures[task_id] = future
        return task_id

    def _exec_family_invite(self, task_id: str, parent_id: int, invite_email: str):
        from automation.family_manage import invite_family_member
        try:
            if self._is_cancelled(task_id):
                return
            result = asyncio.run(invite_family_member(parent_id, invite_email))
            if result:
                self._finish_task(task_id, "done")
            else:
                self._finish_task(task_id, "failed", error="邀请发送失败")
        except Exception as e:
            if not self._is_cancelled(task_id):
                logger.exception("邀请家庭组成员失败: parent_id=%s, email=%s", parent_id, invite_email)
                self._finish_task(task_id, "failed", error=e)

    def run_family_kick(self, parent_id: int, email: str, member_email: str):
        task_id, _ = self._create_task("family_kick", parent_id, email, kick_email=member_email)
        future = self._pool.submit(self._exec_family_kick, task_id, parent_id, member_email)
        self._futures[task_id] = future
        return task_id

    def _exec_family_kick(self, task_id: str, parent_id: int, member_email: str):
        from automation.family_manage import kick_family_member
        try:
            if self._is_cancelled(task_id):
                return
            result = asyncio.run(kick_family_member(parent_id, member_email))
            if result:
                self._finish_task(task_id, "done")
            else:
                self._finish_task(task_id, "failed", error="踢出成员失败")
        except Exception as e:
            if not self._is_cancelled(task_id):
                logger.exception("踢出家庭组成员失败: parent_id=%s, email=%s", parent_id, member_email)
                self._finish_task(task_id, "failed", error=e)

    # ──────────── 年龄认证 ────────────

    def run_age_verify(self, member_id: int, email: str):
        task_id, _ = self._create_task("age_verify", member_id, email)
        future = self._pool.submit(self._exec_age_verify, task_id, member_id)
        self._futures[task_id] = future
        return task_id

    def _exec_age_verify(self, task_id: str, member_id: int):
        from automation.age_verify import age_verify_member
        try:
            if self._is_cancelled(task_id):
                return
            result = asyncio.run(age_verify_member(member_id))
            if result["success"]:
                self._finish_task(task_id, "done")
            else:
                self._finish_task(task_id, "failed", error=result["message"])
        except Exception as e:
            if not self._is_cancelled(task_id):
                logger.exception("年龄认证失败: member_id=%s", member_id)
                self._finish_task(task_id, "failed", error=e)

    # ──────────── 成员全流程执行 ────────────

    def _exec(self, task_id: str, member_ids: list):
        from cli.auto_cmd import run_member_flow

        try:
            for i, mid in enumerate(member_ids):
                if self._is_cancelled(task_id):
                    logger.info("任务已取消，跳过: member_id=%s", mid)
                    return
                logger.info("_exec 开始执行成员: member_id=%s, task_id=%s", mid, task_id)
                asyncio.run(run_member_flow(mid))
                logger.info("_exec 成员执行完成: member_id=%s", mid)
                with self._lock:
                    self._tasks[task_id]["progress"] = i + 1
            self._finish_task(task_id, "done")
        except Exception as e:
            if not self._is_cancelled(task_id):
                logger.exception("成员流程执行失败: task_id=%s", task_id)
                self._finish_task(task_id, "failed", error=e)


task_manager = TaskManager()
