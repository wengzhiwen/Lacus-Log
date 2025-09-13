"""机师分成计算工具模块

提供机师分成比例查询和计算的相关工具函数。
注意：mongoengine 的动态属性在pylint中会触发 no-member 误报，这里统一抑制。
"""
# pylint: disable=no-member
from decimal import Decimal

from models.pilot import PilotCommission
from utils.logging_setup import get_logger
from utils.timezone_helper import local_to_utc

# 创建日志器
logger = get_logger('commission_helper')


def get_pilot_commission_rate_for_date(pilot_id, target_date):
    """获取机师在特定日期的有效分成比例
    
    Args:
        pilot_id: 机师ID
        target_date: 目标日期（本地时间）
        
    Returns:
        tuple: (commission_rate, effective_date, remark)
            - commission_rate: 分成比例（0-50，表示0%-50%）
            - effective_date: 生效日期（UTC时间）
            - remark: 备注说明
    """
    logger.debug(f"获取机师 {pilot_id} 在日期 {target_date} 的分成比例")

    # 将目标日期转换为UTC时间（当天00:00:00）
    target_utc = local_to_utc(target_date.replace(hour=0, minute=0, second=0, microsecond=0))

    logger.debug(f"目标日期UTC时间: {target_utc}")

    # 查询机师的所有有效调整记录，按调整日升序排列
    commissions = PilotCommission.objects(pilot_id=pilot_id, is_active=True).order_by('adjustment_date')
    commission_list = list(commissions)

    logger.debug(f"机师 {pilot_id} 的有效调整记录数量: {len(commission_list)}")

    if not commission_list:
        # 如果没有记录，返回默认20%
        logger.debug(f"机师 {pilot_id} 无调整记录，使用默认分成比例20%")
        return 20.0, None, "默认分成比例"

    # 根据目标日期找到生效的分成记录
    # 找到调整日小于等于目标日期的最后一条记录
    effective_commission = None
    for commission in reversed(commission_list):  # 从最新记录开始查找
        logger.debug(f"检查调整记录: 调整日={commission.adjustment_date}, 分成比例={commission.commission_rate}%")
        if commission.adjustment_date <= target_utc:
            effective_commission = commission
            logger.debug(f"找到生效记录: 调整日={commission.adjustment_date}, 分成比例={commission.commission_rate}%")
            break

    # 如果没有找到生效的记录（所有记录的调整日都是未来日期），返回默认值
    if effective_commission is None:
        logger.debug(f"机师 {pilot_id} 所有调整记录都是未来日期，使用默认分成比例20%")
        return 20.0, None, "默认分成比例"

    logger.debug(f"机师 {pilot_id} 在日期 {target_date} 的生效分成比例: {effective_commission.commission_rate}%")

    return effective_commission.commission_rate, effective_commission.adjustment_date, effective_commission.remark


def calculate_commission_distribution(commission_rate):
    """根据分成比例计算机师和公司的收入分配
    
    Args:
        commission_rate: 机师分成比例（0-50，表示0%-50%）
        
    Returns:
        dict: 包含机师收入比例、公司收入比例和计算公式
    """
    logger.debug(f"计算分成分配，机师分成比例: {commission_rate}%")

    # 固定参数
    BASE_RATE = 50.0  # 50%
    COMPANY_RATE = 42.0  # 42%

    # 机师收入 = (分成比例/50%) * 42%
    pilot_income = (commission_rate / BASE_RATE) * COMPANY_RATE

    # 公司收入 = 42% - 机师收入
    company_income = COMPANY_RATE - pilot_income

    logger.debug("分成分配计算结果:")
    logger.debug(f"  - 机师收入比例: {pilot_income:.2f}%")
    logger.debug(f"  - 公司收入比例: {company_income:.2f}%")
    logger.debug(f"  - 计算公式: ({commission_rate}%/50%) * 42% = {pilot_income:.2f}%")

    return {'pilot_income': pilot_income, 'company_income': company_income, 'calculation_formula': f'({commission_rate}%/50%) * 42% = {pilot_income:.2f}%'}


def calculate_commission_amounts(revenue_amount, commission_rate):
    """计算具体的分成金额
    
    Args:
        revenue_amount: 流水金额
        commission_rate: 机师分成比例（0-50，表示0%-50%）
        
    Returns:
        dict: 包含机师分成金额和公司分成金额
    """
    logger.debug(f"计算分成金额，流水: {revenue_amount}元，机师分成比例: {commission_rate}%")

    # 获取分成分配比例
    distribution = calculate_commission_distribution(commission_rate)

    # 计算具体金额
    pilot_amount = Decimal(str(revenue_amount)) * Decimal(str(distribution['pilot_income'])) / Decimal('100')
    company_amount = Decimal(str(revenue_amount)) * Decimal(str(distribution['company_income'])) / Decimal('100')

    logger.debug("分成金额计算结果:")
    logger.debug(f"  - 机师分成: {revenue_amount} × {distribution['pilot_income']:.2f}% = {pilot_amount:.2f}元")
    logger.debug(f"  - 公司分成: {revenue_amount} × {distribution['company_income']:.2f}% = {company_amount:.2f}元")

    return {
        'pilot_amount': pilot_amount,
        'company_amount': company_amount,
        'pilot_rate': distribution['pilot_income'],
        'company_rate': distribution['company_income']
    }
