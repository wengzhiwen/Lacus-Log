/**
 * Recruit API Client
 * 封装所有与招募模块相关的REST API请求
 */

const RecruitAPI = (() => {
  const showLoader = () => {
    let loader = document.getElementById('loading-overlay');
    if (loader) loader.style.display = 'flex';
  };

  const hideLoader = () => {
    let loader = document.getElementById('loading-overlay');
    if (loader) loader.style.display = 'none';
  };

  const apiRequest = async (url, options = {}) => {
    showLoader();
    try {
      const headers = {
        'Content-Type': 'application/json',
        ...options.headers,
      };

      const response = await fetch(url, { 
        ...options, 
        headers,
        credentials: 'include'
      });

      if (!response.ok) {
        let errorMessage = `HTTP 错误: ${response.status}`;
        try {
          const errorPayload = await response.json();
          errorMessage = errorPayload.error?.message || errorMessage;
        } catch (e) {
          // 响应不是JSON格式，使用默认错误信息
        }
        throw new Error(errorMessage);
      }

      const payload = await response.json();
      if (!payload.success) {
        throw new Error(payload.error?.message || '操作失败，但未返回具体错误信息');
      }

      return payload;
    } catch (error) {
      // 使用base.html中定义的全局showMessage函数
      if (window.showMessage) {
        window.showMessage(error.message, 'error');
      }
      throw error; // 重新抛出错误，以便调用方可以进一步处理
    } finally {
      hideLoader();
    }
  };

  return {
    getRecruits: (params) => {
      const url = new URL(`${window.location.origin}/api/recruits`);
      Object.keys(params).forEach(key => url.searchParams.append(key, params[key]));
      return apiRequest(url.toString(), { method: 'GET' });
    },

    getGroupedRecruits: (status = '进行中') => {
      return apiRequest(`/api/recruits/grouped?status=${status}`, { method: 'GET' });
    },

    getRecruitDetail: (id) => {
      return apiRequest(`/api/recruits/${id}`, { method: 'GET' });
    },

    getRecruitChanges: (id, page = 1, pageSize = 20) => {
      return apiRequest(`/api/recruits/${id}/changes?page=${page}&page_size=${pageSize}`, { method: 'GET' });
    },

    getOptions: () => {
      return apiRequest('/api/recruits/options', { method: 'GET' });
    },

    createRecruit: (data) => {
      return apiRequest('/api/recruits', { method: 'POST', body: JSON.stringify(data) });
    },

    updateRecruit: (id, data) => {
      return apiRequest(`/api/recruits/${id}`, { method: 'PUT', body: JSON.stringify(data) });
    },

    interviewDecision: (id, data) => {
      return apiRequest(`/api/recruits/${id}/interview-decision`, { method: 'POST', body: JSON.stringify(data) });
    },

    scheduleTraining: (id, data) => {
      return apiRequest(`/api/recruits/${id}/schedule-training`, { method: 'POST', body: JSON.stringify(data) });
    },

    trainingDecision: (id, data) => {
      return apiRequest(`/api/recruits/${id}/training-decision`, { method: 'POST', body: JSON.stringify(data) });
    },

    scheduleBroadcast: (id, data) => {
      return apiRequest(`/api/recruits/${id}/schedule-broadcast`, { method: 'POST', body: JSON.stringify(data) });
    },

    broadcastDecision: (id, data) => {
      return apiRequest(`/api/recruits/${id}/broadcast-decision`, { method: 'POST', body: JSON.stringify(data) });
    }
  };
})();


