/**
 * 结算方式计算工具函数
 * 提供统一的结算方式查询和显示逻辑
 */

/**
 * 将UTC时间转换为GMT+8本地日期字符串
 * @param {string|Date} utcTime - UTC时间字符串或Date对象
 * @returns {string} YYYY-MM-DD格式的本地日期字符串
 */
function utcToLocalDateString(utcTime) {
  if (!utcTime) {
    throw new Error('UTC时间不能为空');
  }
  
  // 确保是UTC时间
  let utcDate;
  if (typeof utcTime === 'string') {
    // 如果字符串没有Z后缀，添加Z标记为UTC
    const timeStr = utcTime.endsWith('Z') ? utcTime : utcTime + 'Z';
    utcDate = new Date(timeStr);
  } else {
    utcDate = new Date(utcTime);
  }
  
  // 验证日期有效性
  if (isNaN(utcDate.getTime())) {
    throw new Error('无效的UTC时间格式');
  }
  
  // 转换为GMT+8本地时间
  const localDate = new Date(utcDate.getTime() + 8 * 60 * 60 * 1000);
  
  // 提取年月日
  const year = localDate.getUTCFullYear();
  const month = String(localDate.getUTCMonth() + 1).padStart(2, '0');
  const day = String(localDate.getUTCDate()).padStart(2, '0');
  
  return `${year}-${month}-${day}`;
}

/**
 * 获取指定主播在指定日期的生效结算方式
 * @param {string} pilotId - 主播ID
 * @param {string|Date} battleStartTime - 开播开始时间（UTC）
 * @returns {Promise<Object>} 结算方式信息
 */
async function getEffectiveSettlement(pilotId, battleStartTime) {
  if (!pilotId) {
    throw new Error('主播ID不能为空');
  }
  
  if (!battleStartTime) {
    throw new Error('开播开始时间不能为空');
  }
  
  try {
    // 将UTC时间转换为本地日期
    const localDateStr = utcToLocalDateString(battleStartTime);
    
    console.log('正在获取结算方式信息，pilotId:', pilotId, 'date:', localDateStr);
    
    // 调用API获取结算方式
    const response = await fetch(`/api/settlements/${pilotId}/effective?date=${localDateStr}`, {
      credentials: 'include'
    });
    
    if (!response.ok) {
      console.error('结算方式API请求失败:', response.status, response.statusText);
      throw new Error('无法获取结算方式信息');
    }
    
    const result = await response.json();
    console.log('结算方式API响应:', result);
    
    if (!result.success) {
      console.error('结算方式API返回错误:', result.error);
      throw new Error(result.error?.message || '获取结算方式信息失败');
    }
    
    return result.data;
  } catch (error) {
    console.error('获取结算方式失败:', error);
    throw error;
  }
}

/**
 * 渲染结算方式信息到页面元素
 * @param {Object} settlementData - 结算方式数据
 * @param {Object} elements - DOM元素映射
 */
function renderSettlementInfo(settlementData, elements) {
  if (!settlementData) {
    console.warn('结算方式数据为空');
    return;
  }

  const settlementTypeDisplay = settlementData.settlement_type_display || '无底薪';
  const isMonthlyBase = settlementData.settlement_type === 'monthly_base';

  // 更新结算方式显示
  if (elements.settlementTypeDisplay) {
    elements.settlementTypeDisplay.textContent = settlementTypeDisplay;
    if (isMonthlyBase) {
      elements.settlementTypeDisplay.style.color = '#d32f2f';
      elements.settlementTypeDisplay.style.fontWeight = '600';
    }
  }

  // 更新生效日期显示
  if (elements.effectiveDateDisplay) {
    elements.effectiveDateDisplay.textContent = settlementData.effective_date || '--';
  }

  // 更新当前结算方式显示（用于底薪申请页）
  if (elements.currentSettlement) {
    elements.currentSettlement.textContent = settlementTypeDisplay;
    if (isMonthlyBase) {
      elements.currentSettlement.style.color = '#d32f2f';
      elements.currentSettlement.style.fontWeight = '600';
    }
  }

  // 更新结算方式快照（用于底薪申请页）
  if (elements.settlementTypeSnapshot) {
    elements.settlementTypeSnapshot.value = settlementTypeDisplay;
    if (isMonthlyBase) {
      elements.settlementTypeSnapshot.style.color = '#d32f2f';
      elements.settlementTypeSnapshot.style.fontWeight = '600';
    }
  }

  console.log('结算方式信息渲染完成:', settlementData);
}

/**
 * 检查是否应该显示申请底薪按钮
 * @param {Object} settlementData - 结算方式数据
 * @returns {boolean} 是否应该显示申请按钮
 */
function shouldShowApplyButton(settlementData, options = {}) {
  if (!settlementData) {
    return false;
  }

  const isEligibleSettlement = settlementData.settlement_type === 'daily_base' || settlementData.settlement_type === 'monthly_base';
  if (!isEligibleSettlement) {
    return false;
  }

  if (options.recordStatus && options.recordStatus !== 'ended') {
    return false;
  }

  return true;
}

/**
 * 显示或隐藏申请底薪按钮
 * @param {Object} settlementData - 结算方式数据
 * @param {HTMLElement} applyButton - 申请按钮元素
 */
function toggleApplyButton(settlementData, applyButton, options = {}) {
  if (!applyButton) {
    return;
  }

  if (shouldShowApplyButton(settlementData, options)) {
    applyButton.style.display = '';
  } else {
    applyButton.style.display = 'none';
  }
}

// 导出函数供其他模块使用
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    utcToLocalDateString,
    getEffectiveSettlement,
    renderSettlementInfo,
    shouldShowApplyButton,
    toggleApplyButton
  };
}
