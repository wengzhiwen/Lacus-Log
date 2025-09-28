"""系统内置定时任务调度模块。

不依赖系统级 cron，由应用内置的 APScheduler 负责。
引入 MongoDB 任务计划令牌，保证同一计划仅执行一次。
"""

from datetime import datetime, timezone
from typing import Any, Optional

from utils.job_token import JobPlan, consume_fire, plan_fire
from utils.logging_setup import get_logger
from utils.timezone_helper import get_current_utc_time

logger = get_logger('scheduler')

_scheduler: Optional[Any] = None


def _ensure_scheduler():
    global _scheduler  # noqa: PLW0603 - 模块级单例
    if _scheduler is None:
        # 延迟导入，避免在未安装依赖或静态检查阶段报错
        from apscheduler.schedulers.background import \
            BackgroundScheduler  # type: ignore
        _scheduler = BackgroundScheduler(timezone='UTC')
    return _scheduler


def init_scheduled_jobs(flask_app) -> None:
    """初始化并启动系统内置的定时任务。

    约定：
    - 任务逻辑应为可直接调用的纯函数，必要时自行创建应用上下文。
    - 调度器使用后台线程运行。
    """
    sched = _ensure_scheduler()

    # 确保 JobPlan 索引（与调度强相关，放在此处）
    try:
        JobPlan.ensure_indexes()
        logger.info('已确保 JobPlan 索引创建完成')
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('确保 JobPlan 索引失败：%s', exc)

    # 使用 CronTrigger
    from apscheduler.triggers.cron import CronTrigger  # type: ignore

    # 未开播提醒：UTC 12:00 (GMT+8 20:00)
    unstarted_trigger = CronTrigger(hour=12, minute=0, timezone='UTC')

    # 征召日报：UTC 16:05 (GMT+8 00:05)
    recruit_daily_trigger = CronTrigger(hour=16, minute=5, timezone='UTC')

    # 开播日报：UTC 16:02 (GMT+8 00:02)
    daily_report_trigger = CronTrigger(hour=16, minute=2, timezone='UTC')

    # 工具：根据 CronTrigger 计算下一次运行时间（UTC）
    def _next_fire_utc(trigger) -> datetime:
        now_utc = get_current_utc_time()
        next_dt = trigger.get_next_fire_time(previous_fire_time=None, now=now_utc)
        # APScheduler 返回的是naive或aware取决于构造；统一转为UTC aware
        if next_dt is None:
            return now_utc
        if next_dt.tzinfo is None:
            return next_dt.replace(tzinfo=timezone.utc)
        return next_dt.astimezone(timezone.utc)

    # 每天 GMT+8 20:00 执行未开播提醒 => UTC 12:00
    def run_unstarted_wrapper():
        # 延迟导入避免循环依赖
        from routes.report_mail import run_unstarted_report_job

        # 以分钟为粒度的计划时间（向下取整到分钟）
        fire_dt_utc = get_current_utc_time().replace(second=0, microsecond=0)
        if not consume_fire('daily_unstarted_report', fire_dt_utc):
            logger.info('跳过执行：daily_unstarted_report（计划令牌不存在）')
            return
        with flask_app.app_context():
            result = run_unstarted_report_job(triggered_by='scheduler@daily-20:00+08')
            logger.info('定时任务 run_unstarted_report_job 完成：%s', result)
        # 刷新下一次计划
        plan_fire('daily_unstarted_report', _next_fire_utc(unstarted_trigger))

    # 每天 GMT+8 00:05 执行征召日报 => UTC 16:05 (前一天)
    def run_recruit_daily_wrapper():
        # 延迟导入避免循环依赖
        from routes.report_mail import run_recruit_daily_report_job
        fire_dt_utc = get_current_utc_time().replace(second=0, microsecond=0)
        if not consume_fire('daily_recruit_daily_report', fire_dt_utc):
            logger.info('跳过执行：daily_recruit_daily_report（计划令牌不存在）')
            return
        with flask_app.app_context():
            result = run_recruit_daily_report_job(triggered_by='scheduler@daily-00:05+08')
            logger.info('定时任务 run_recruit_daily_report_job 完成：%s', result)
        plan_fire('daily_recruit_daily_report', _next_fire_utc(recruit_daily_trigger))

    # 每天 GMT+8 00:02 执行开播日报 => UTC 16:02 (前一天)
    def run_daily_report_wrapper():
        # 延迟导入避免循环依赖
        from routes.report_mail import run_daily_report_job
        fire_dt_utc = get_current_utc_time().replace(second=0, microsecond=0)
        if not consume_fire('daily_report', fire_dt_utc):
            logger.info('跳过执行：daily_report（计划令牌不存在）')
            return
        with flask_app.app_context():
            result = run_daily_report_job(triggered_by='scheduler@daily-00:02+08')
            logger.info('定时任务 run_daily_report_job 完成：%s', result)
        plan_fire('daily_report', _next_fire_utc(daily_report_trigger))

    sched.add_job(run_unstarted_wrapper, unstarted_trigger, id='daily_unstarted_report', replace_existing=True, max_instances=1)
    # 启动时写入下一次计划
    try:
        plan_fire('daily_unstarted_report', _next_fire_utc(unstarted_trigger))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('写入未开播提醒下一次计划失败：%s', exc)

    sched.add_job(run_recruit_daily_wrapper, recruit_daily_trigger, id='daily_recruit_daily_report', replace_existing=True, max_instances=1)
    try:
        plan_fire('daily_recruit_daily_report', _next_fire_utc(recruit_daily_trigger))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('写入征召日报下一次计划失败：%s', exc)

    sched.add_job(run_daily_report_wrapper, daily_report_trigger, id='daily_report', replace_existing=True, max_instances=1)
    try:
        plan_fire('daily_report', _next_fire_utc(daily_report_trigger))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('写入开播日报下一次计划失败：%s', exc)

    if not sched.running:
        sched.start(paused=False)
        logger.info('APScheduler 已启动，任务数：%d', len(sched.get_jobs()))
