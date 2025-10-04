
/**
 * UI Helpers
 * 负责显示成功/错误消息、管理加载状态等
 */
const ErrorHandler = {
  showError: (message) => {
    const errorContainer = document.getElementById('error-container');
    if (errorContainer) {
      errorContainer.textContent = message;
      errorContainer.style.display = 'block';
      // 5秒后自动隐藏
      setTimeout(() => {
        errorContainer.style.display = 'none';
      }, 5000);
    } else {
      alert(`错误: ${message}`);
    }
  },

  showSuccess: (message) => {
    const successContainer = document.getElementById('success-container');
    if (successContainer) {
      successContainer.textContent = message;
      successContainer.style.display = 'block';
      // 3秒后自动隐藏
      setTimeout(() => {
        successContainer.style.display = 'none';
      }, 3000);
    } else {
      alert(message);
    }
  },

  clearMessages: () => {
    const errorContainer = document.getElementById('error-container');
    if (errorContainer) errorContainer.style.display = 'none';

    const successContainer = document.getElementById('success-container');
    if (successContainer) successContainer.style.display = 'none';
  }
};

const UILoader = {
  show: () => {
    let loader = document.getElementById('loading-overlay');
    if (!loader) {
      loader = document.createElement('div');
      loader.id = 'loading-overlay';
      loader.innerHTML = '<div class="spinner"></div>';
      document.body.appendChild(loader);
    }
    loader.style.display = 'flex';
  },

  hide: () => {
    const loader = document.getElementById('loading-overlay');
    if (loader) {
      loader.style.display = 'none';
    }
  }
};

// 在base.html中可能需要添加以下CSS
/*
#error-container, #success-container {
  padding: 15px;
  margin-bottom: 20px;
  border-radius: 4px;
  color: #fff;
  display: none;
}
#error-container { background-color: #d32f2f; }
#success-container { background-color: #388e3c; }

#loading-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background-color: rgba(255, 255, 255, 0.7);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 9999;
}
.spinner {
  border: 4px solid rgba(0, 0, 0, 0.1);
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border-left-color: var(--brand);
  animation: spin 1s ease infinite;
}
@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}
*/
