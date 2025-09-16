"""系统内置定时任务调度模块。

不依赖系统级 cron，由应用内置的 APScheduler 负责。
"""

from typing import Any, Optional

from utils.logging_setup import get_logger

logger = get_logger('scheduler')

_scheduler: Optional[Any] = None


def _ensure_scheduler():
    global _scheduler  # noqa: PLW0603 - 模块级单例
    if _scheduler is None:
        # 延迟导入，避免在未安装依赖或静态检查阶段报错
        from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore
        _scheduler = BackgroundScheduler(timezone='UTC')
    return _scheduler


def init_scheduled_jobs(flask_app) -> None:
    """初始化并启动系统内置的定时任务。

    约定：
    - 任务逻辑应为可直接调用的纯函数，必要时自行创建应用上下文。
    - 调度器使用后台线程运行。
    """
    sched = _ensure_scheduler()

    # 每天 GMT+8 20:00 执行 => UTC 12:00
    def run_unstarted_wrapper():
        # 延迟导入避免循环依赖
        from routes.report_mail import run_unstarted_report_job
        with flask_app.app_context():
            result = run_unstarted_report_job(triggered_by='scheduler@daily-20:00+08')
            logger.info('定时任务 run_unstarted_report_job 完成：%s', result)

    # 使用 CronTrigger：UTC 12:00
    from apscheduler.triggers.cron import CronTrigger  # type: ignore
    trigger = CronTrigger(hour=12, minute=0, timezone='UTC')
    sched.add_job(run_unstarted_wrapper, trigger, id='daily_unstarted_report', replace_existing=True)

    if not sched.running:
        sched.start(paused=False)
        logger.info('APScheduler 已启动，任务数：%d', len(sched.get_jobs()))
