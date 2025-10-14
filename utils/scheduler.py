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

    try:
        JobPlan.ensure_indexes()
        logger.info('已确保 JobPlan 索引创建完成')
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('确保 JobPlan 索引失败：%s', exc)

    from apscheduler.triggers.cron import CronTrigger  # type: ignore

    unstarted_trigger = CronTrigger(hour=12, minute=0, timezone='UTC')

    # 线上主播未开播提醒：每日 GMT+8 17:00 触发（UTC 09:00）
    online_pilot_unstarted_trigger = CronTrigger(hour=9, minute=0, timezone='UTC')

    recruit_daily_trigger = CronTrigger(hour=16, minute=5, timezone='UTC')

    # 开播邮件日报：每日 GMT+8 15:00 触发（UTC 07:00）
    daily_report_trigger = CronTrigger(hour=7, minute=0, timezone='UTC')

    # 开播邮件月报：每日 GMT+8 15:02 触发（UTC 07:02），发送"前一自然日所在月"的月报
    monthly_mail_report_trigger = CronTrigger(hour=7, minute=2, timezone='UTC')

    def _next_fire_utc(trigger) -> datetime:
        now_utc = get_current_utc_time()
        next_dt = trigger.get_next_fire_time(previous_fire_time=None, now=now_utc)
        if next_dt is None:
            return now_utc
        if next_dt.tzinfo is None:
            return next_dt.replace(tzinfo=timezone.utc)
        return next_dt.astimezone(timezone.utc)

    def run_unstarted_wrapper():
        from routes.report_mail import run_unstarted_report_job

        fire_dt_utc = get_current_utc_time().replace(second=0, microsecond=0)
        if not consume_fire('daily_unstarted_report', fire_dt_utc):
            logger.info('跳过执行：daily_unstarted_report（计划令牌不存在）')
            return
        with flask_app.app_context():
            result = run_unstarted_report_job(triggered_by='scheduler@daily-20:00+08')
            logger.info('定时任务 run_unstarted_report_job 完成：%s', result)
        plan_fire('daily_unstarted_report', _next_fire_utc(unstarted_trigger))

    def run_online_pilot_unstarted_wrapper():
        from routes.report_mail import run_online_pilot_unstarted_report_job

        fire_dt_utc = get_current_utc_time().replace(second=0, microsecond=0)
        if not consume_fire('daily_online_pilot_unstarted_report', fire_dt_utc):
            logger.info('跳过执行：daily_online_pilot_unstarted_report（计划令牌不存在）')
            return
        with flask_app.app_context():
            result = run_online_pilot_unstarted_report_job(triggered_by='scheduler@daily-17:00+08')
            logger.info('定时任务 run_online_pilot_unstarted_report_job 完成：%s', result)
        plan_fire('daily_online_pilot_unstarted_report', _next_fire_utc(online_pilot_unstarted_trigger))

    def run_recruit_daily_wrapper():
        from routes.report_mail import run_recruit_daily_report_job
        fire_dt_utc = get_current_utc_time().replace(second=0, microsecond=0)
        if not consume_fire('daily_recruit_daily_report', fire_dt_utc):
            logger.info('跳过执行：daily_recruit_daily_report（计划令牌不存在）')
            return
        with flask_app.app_context():
            result = run_recruit_daily_report_job(triggered_by='scheduler@daily-00:05+08')
            logger.info('定时任务 run_recruit_daily_report_job 完成：%s', result)
        plan_fire('daily_recruit_daily_report', _next_fire_utc(recruit_daily_trigger))

    def run_daily_report_wrapper():
        from routes.report_mail import run_daily_report_job
        fire_dt_utc = get_current_utc_time().replace(second=0, microsecond=0)
        if not consume_fire('daily_report', fire_dt_utc):
            logger.info('跳过执行：daily_report（计划令牌不存在）')
            return
        with flask_app.app_context():
            result = run_daily_report_job(triggered_by='scheduler@daily-15:00+08')
            logger.info('定时任务 run_daily_report_job 完成：%s', result)
        plan_fire('daily_report', _next_fire_utc(daily_report_trigger))

    def run_monthly_mail_report_wrapper():
        from routes.report_mail import \
            run_monthly_mail_report_job  # type: ignore  # pylint: disable=import-error,no-name-in-module
        fire_dt_utc = get_current_utc_time().replace(second=0, microsecond=0)
        if not consume_fire('daily_monthly_mail_report', fire_dt_utc):
            logger.info('跳过执行：daily_monthly_mail_report（计划令牌不存在）')
            return
        with flask_app.app_context():
            result = run_monthly_mail_report_job(triggered_by='scheduler@daily-15:02+08')
            logger.info('定时任务 run_monthly_mail_report_job 完成：%s', result)
        plan_fire('daily_monthly_mail_report', _next_fire_utc(monthly_mail_report_trigger))

    sched.add_job(run_unstarted_wrapper, unstarted_trigger, id='daily_unstarted_report', replace_existing=True, max_instances=1)
    try:
        plan_fire('daily_unstarted_report', _next_fire_utc(unstarted_trigger))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('写入未开播提醒下一次计划失败：%s', exc)

    sched.add_job(run_online_pilot_unstarted_wrapper,
                  online_pilot_unstarted_trigger,
                  id='daily_online_pilot_unstarted_report',
                  replace_existing=True,
                  max_instances=1)
    try:
        plan_fire('daily_online_pilot_unstarted_report', _next_fire_utc(online_pilot_unstarted_trigger))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('写入线上主播未开播提醒下一次计划失败：%s', exc)

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

    # 新增：开播邮件月报（每日发送上一自然日所在月的月报）
    sched.add_job(run_monthly_mail_report_wrapper, monthly_mail_report_trigger, id='daily_monthly_mail_report', replace_existing=True, max_instances=1)
    try:
        plan_fire('daily_monthly_mail_report', _next_fire_utc(monthly_mail_report_trigger))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('写入开播邮件月报下一次计划失败：%s', exc)

    if not sched.running:
        sched.start(paused=False)
        logger.info('APScheduler 已启动，任务数：%d', len(sched.get_jobs()))
