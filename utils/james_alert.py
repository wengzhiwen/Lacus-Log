#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
詹姆斯的关注 - 低业绩不努力主播告警模块

当开播记录保存时，自动检查主播业绩情况，
如果满足特定条件则发送警告邮件。
"""

import threading
from datetime import datetime
from decimal import Decimal

# pylint: disable=no-member
from models.pilot import Gender
from models.recruit import Recruit
from models.user import User
from utils.commission_helper import get_pilot_commission_rate_for_date
from utils.logging_setup import get_logger
from utils.mail_utils import send_email_md
from utils.timezone_helper import get_current_local_time, utc_to_local

logger = get_logger('james_alert')


def check_james_alert_trigger_conditions(battle_record, old_record=None):
    """
    检查是否满足詹姆斯关注的触发条件
    
    Args:
        battle_record: 开播记录对象
        old_record: 编辑前的记录对象（仅编辑时提供）
        
    Returns:
        bool: 是否满足触发条件
        str: 跳过原因（如果不满足条件）
    """
    try:
        if battle_record.revenue_amount <= 0:
            return False, f"流水为{battle_record.revenue_amount}元，不符合触发条件（需要>0）"

        if old_record is not None:
            if battle_record.revenue_amount == old_record.revenue_amount:
                return False, f"编辑未改变流水金额（{battle_record.revenue_amount}元），不触发告警"

        if battle_record.revenue_amount >= 250:
            return False, f"流水为{battle_record.revenue_amount}元，不符合触发条件（需要<250）"

        duration_hours = battle_record.duration_hours or 0
        if duration_hours >= 7:
            return False, f"播时为{duration_hours}小时，不符合触发条件（需要<7）"

        if battle_record.base_salary < 100:
            return False, f"底薪为{battle_record.base_salary}元，不符合触发条件（需要>=100）"

        return True, "所有触发条件均满足"

    except Exception as e:
        logger.error(f"检查詹姆斯关注触发条件时发生异常: {e}")
        return False, f"检查触发条件时发生异常: {e}"


def check_james_alert_calculation_conditions(pilot_stats):
    """
    检查是否满足詹姆斯关注的运算条件
    
    Args:
        pilot_stats: 主播业绩统计数据字典，包含month_stats, week_stats, three_day_stats
        
    Returns:
        bool: 是否满足运算条件
        str: 跳过原因（如果不满足条件）
    """
    try:
        month_stats = pilot_stats.get('month_stats', {})
        week_stats = pilot_stats.get('week_stats', {})
        three_day_stats = pilot_stats.get('three_day_stats', {})

        three_day_avg_hours = three_day_stats.get('avg_hours', 0)
        if three_day_avg_hours >= 7:
            return False, f"近3日平均时数为{three_day_avg_hours}小时，不符合告警条件（需要<7）"

        three_day_profit = three_day_stats.get('operating_profit', 0)
        if three_day_profit >= 100:
            return False, f"近3日盈亏为{three_day_profit}元，不符合告警条件（需要<100）"

        week_profit = week_stats.get('operating_profit', 0)
        if week_profit >= 250:
            return False, f"近7日盈亏为{week_profit}元，不符合告警条件（需要<250）"

        month_profit = month_stats.get('operating_profit', 0)
        if month_profit >= 0:
            return False, f"本月运营利润估算为{month_profit}元，不符合告警条件（需要<0）"

        return True, "所有运算条件均满足"

    except Exception as e:
        logger.error(f"检查詹姆斯关注运算条件时发生异常: {e}")
        return False, f"检查运算条件时发生异常: {e}"


def get_pilot_basic_info(pilot):
    """
    获取主播基本信息
    
    Args:
        pilot: 主播对象
        
    Returns:
        dict: 主播基本信息
    """
    try:
        age = "未知"
        if pilot.birth_year:
            current_year = datetime.now().year
            age = current_year - pilot.birth_year

        if pilot.gender == Gender.MALE:
            gender_icon = "♂"
        elif pilot.gender == Gender.FEMALE:
            gender_icon = "♀"
        else:
            gender_icon = "?"

        current_date = get_current_local_time().date()
        commission_rate, _, _ = get_pilot_commission_rate_for_date(pilot.id, current_date)

        recruiter_name = "未知"
        try:
            latest_recruit = Recruit.objects.filter(pilot=pilot).order_by('-created_at').first()
            if latest_recruit and latest_recruit.recruiter:
                recruiter_name = latest_recruit.recruiter.nickname or latest_recruit.recruiter.username
        except Exception as e:
            logger.debug(f"获取主播{pilot.nickname}的招募负责人失败: {e}")

        return {
            'nickname': pilot.nickname or "未知",
            'real_name': pilot.real_name or "未知",
            'age': age,
            'gender_icon': gender_icon,
            'hometown': pilot.hometown or "未知",
            'rank': pilot.rank.value if pilot.rank else "未知",
            'owner': pilot.owner.nickname if pilot.owner else "无",
            'commission_rate': commission_rate,
            'recruiter_name': recruiter_name,
            'status': pilot.get_effective_status_display()
        }

    except Exception as e:
        logger.error(f"获取主播基本信息时发生异常: {e}")
        return {
            'nickname': pilot.nickname or "未知",
            'real_name': "未知",
            'age': "未知",
            'gender_icon': "?",
            'hometown': "未知",
            'rank': "未知",
            'owner': "无",
            'commission_rate': 20.0,
            'recruiter_name': "未知"
        }


def format_number(value):
    """格式化数字，添加千分位分隔符"""
    if isinstance(value, (int, float, Decimal)):
        return f"{value:,.2f}"
    return str(value)


def format_duration(value):
    """格式化时长"""
    if isinstance(value, (int, float)):
        return f"{value:.1f}"
    return str(value)


def build_james_alert_email_content(pilot_info, pilot_stats):
    """
    构建詹姆斯关注警告邮件内容
    
    Args:
        pilot_info: 主播基本信息
        pilot_stats: 主播业绩统计数据
        
    Returns:
        str: Markdown格式的邮件内容
    """
    try:
        month_stats = pilot_stats.get('month_stats', {})
        week_stats = pilot_stats.get('week_stats', {})
        three_day_stats = pilot_stats.get('three_day_stats', {})
        recent_records = pilot_stats.get('recent_records', [])

        content = f"""# {pilot_info['nickname']}（{pilot_info['real_name']}）正在受到詹姆斯的关注


- {pilot_info['age']}岁{pilot_info['gender_icon']} **籍贯** {pilot_info['hometown']}
- **主播分类**：{pilot_info['rank']}
- **分成比例**：{pilot_info['commission_rate']}%
- **直属运营**：{pilot_info['owner']}
- **招募负责人**：{pilot_info['recruiter_name']}
- **主播状态**：{pilot_info['status']}


| 指标 | 数值 |
|------|------|
| 开播记录数 | {month_stats.get('record_count', 0)}条 |
| 开播时数 | {format_duration(month_stats.get('total_hours', 0))}小时 [平均{format_duration(month_stats.get('avg_hours', 0))}小时] |
| 累计流水 | {format_number(month_stats.get('total_revenue', 0))}元 [日均{format_number(month_stats.get('daily_avg_revenue', 0))}元] |
| 累计底薪 | {format_number(month_stats.get('total_basepay', 0))}元 [日均{format_number(month_stats.get('daily_avg_basepay', 0))}元] |
| 累计返点 | {format_number(month_stats.get('total_rebate', 0))}元 |
| 累计公司分成 | {format_number(month_stats.get('total_company_share', 0))}元 |
| 运营利润估算 | {format_number(month_stats.get('operating_profit', 0))}元 [日均{format_number(month_stats.get('daily_avg_operating_profit', 0))}元] |


| 指标 | 数值 |
|------|------|
| 开播记录数 | {week_stats.get('record_count', 0)}条 |
| 开播时数 | {format_duration(week_stats.get('total_hours', 0))}小时 [平均{format_duration(week_stats.get('avg_hours', 0))}小时] |
| 累计流水 | {format_number(week_stats.get('total_revenue', 0))}元 [日均{format_number(week_stats.get('daily_avg_revenue', 0))}元] |
| 累计底薪 | {format_number(week_stats.get('total_basepay', 0))}元 [日均{format_number(week_stats.get('daily_avg_basepay', 0))}元] |
| 累计返点 | {format_number(week_stats.get('total_rebate', 0))}元 |
| 累计公司分成 | {format_number(week_stats.get('total_company_share', 0))}元 |
| 近日盈亏（不计返点） | {format_number(week_stats.get('operating_profit', 0))}元 [日均{format_number(week_stats.get('daily_avg_operating_profit', 0))}元] |


| 指标 | 数值 |
|------|------|
| 开播记录数 | {three_day_stats.get('record_count', 0)}条 |
| 开播时数 | {format_duration(three_day_stats.get('total_hours', 0))}小时 [平均{format_duration(three_day_stats.get('avg_hours', 0))}小时] |
| 累计流水 | {format_number(three_day_stats.get('total_revenue', 0))}元 [日均{format_number(three_day_stats.get('daily_avg_revenue', 0))}元] |
| 累计底薪 | {format_number(three_day_stats.get('total_basepay', 0))}元 [日均{format_number(three_day_stats.get('daily_avg_basepay', 0))}元] |
| 累计返点 | {format_number(three_day_stats.get('total_rebate', 0))}元 |
| 累计公司分成 | {format_number(three_day_stats.get('total_company_share', 0))}元 |
| 近日盈亏（不计返点） | {format_number(three_day_stats.get('operating_profit', 0))}元 [日均{format_number(three_day_stats.get('daily_avg_operating_profit', 0))}元] |


| 开播时间 | 结束时间 | 播时 | 流水 | 底薪 | 备注 |
|----------|----------|------|------|------|------|"""

        for record in recent_records[:10]:  # 只显示前10条记录以适应邮件格式
            start_time = utc_to_local(record.start_time).strftime('%Y-%m-%d %H:%M') if record.start_time else '-'
            end_time = utc_to_local(record.end_time).strftime('%Y-%m-%d %H:%M') if record.end_time else '-'
            duration = format_duration(record.duration_hours) if record.duration_hours else '0.0'
            revenue = format_number(record.revenue_amount)
            base_salary = format_number(record.base_salary)
            notes = record.notes or '-'

            content += f"\n| {start_time} | {end_time} | {duration}小时 | {revenue}元 | {base_salary}元 | {notes} |"

        return content

    except Exception as e:
        logger.error(f"构建詹姆斯关注邮件内容时发生异常: {e}")
        return f"# 邮件内容生成失败\n\n主播：{pilot_info.get('nickname', '未知')}\n\n错误信息：{e}"


def get_alert_recipients():
    """
    获取告警邮件收件人列表
    
    Returns:
        list: 邮箱地址列表
    """
    try:
        recipients = []
        users = User.objects.filter(active=True).all()

        for user in users:
            if user.has_role('gicho') or user.has_role('kancho'):
                if user.email and user.email.strip():
                    recipients.append(user.email.strip())

        recipients = list(set(recipients))
        logger.debug(f"获取到{len(recipients)}个告警邮件收件人")

        return recipients

    except Exception as e:
        logger.error(f"获取告警邮件收件人时发生异常: {e}")
        return []


def send_james_alert_email(pilot_info, pilot_stats):
    """
    发送詹姆斯关注警告邮件
    
    Args:
        pilot_info: 主播基本信息
        pilot_stats: 主播业绩统计数据
        
    Returns:
        bool: 发送成功返回True，失败返回False
    """
    try:
        recipients = get_alert_recipients()
        if not recipients:
            logger.warning("没有找到告警邮件收件人，跳过发送")
            return False

        email_content = build_james_alert_email_content(pilot_info, pilot_stats)

        subject = "拉科斯警告 詹姆斯正在关注这个主播"
        success = send_email_md(recipients, subject, email_content)

        if success:
            logger.info(f"詹姆斯关注警告邮件发送成功: 主播{pilot_info['nickname']}，收件人{len(recipients)}个")
        else:
            logger.error(f"詹姆斯关注警告邮件发送失败: 主播{pilot_info['nickname']}")

        return success

    except Exception as e:
        logger.error(f"发送詹姆斯关注警告邮件时发生异常: {e}")
        return False


def process_james_alert_async(battle_record, old_record=None):
    """
    异步处理詹姆斯关注警告逻辑
    
    Args:
        battle_record: 开播记录对象
        old_record: 编辑前的记录对象（仅编辑时提供）
    """

    def _process():
        try:
            pilot = battle_record.pilot
            logger.debug(f"开始处理主播{pilot.nickname}的詹姆斯关注警告检查")

            trigger_ok, trigger_reason = check_james_alert_trigger_conditions(battle_record, old_record)
            if not trigger_ok:
                logger.info(f"主播{pilot.nickname}不触发詹姆斯关注警告: {trigger_reason}")
                return

            from utils.pilot_performance import calculate_pilot_performance_stats

            now_local = get_current_local_time()
            performance_data = calculate_pilot_performance_stats(pilot, now_local)
            month_stats = performance_data['month_stats']
            week_stats = performance_data['week_stats']
            three_day_stats = performance_data['three_day_stats']

            from models.battle_record import BattleRecord
            recent_records = BattleRecord.objects.filter(pilot=pilot).order_by('-start_time').limit(30)

            pilot_stats = {'month_stats': month_stats, 'week_stats': week_stats, 'three_day_stats': three_day_stats, 'recent_records': list(recent_records)}

            calc_ok, calc_reason = check_james_alert_calculation_conditions(pilot_stats)
            if not calc_ok:
                logger.info(f"主播{pilot.nickname}不触发詹姆斯关注告警邮件: {calc_reason}")
                return

            pilot_info = get_pilot_basic_info(pilot)

            success = send_james_alert_email(pilot_info, pilot_stats)
            if success:
                logger.info(f"主播{pilot.nickname}的詹姆斯关注警告邮件已发送")
            else:
                logger.error(f"主播{pilot.nickname}的詹姆斯关注警告邮件发送失败")

        except Exception as e:
            logger.error(f"处理詹姆斯关注警告时发生异常: {e}", exc_info=True)

    thread = threading.Thread(target=_process)
    thread.daemon = True
    thread.start()


def trigger_james_alert_if_needed(battle_record, old_record=None):
    """
    如果需要，触发詹姆斯关注警告检查
    
    这是外部调用的主要接口，在开播记录保存时调用
    
    Args:
        battle_record: 开播记录对象
        old_record: 编辑前的记录对象（仅编辑时提供）
    """
    try:
        if not battle_record or not battle_record.pilot:
            logger.debug("开播记录或主播信息不完整，跳过詹姆斯关注警告检查")
            return

        process_james_alert_async(battle_record, old_record)

    except Exception as e:
        logger.error(f"触发詹姆斯关注警告检查时发生异常: {e}", exc_info=True)
