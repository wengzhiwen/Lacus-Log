/**
 * 招募决策防呆功能
 * 当用户选择"不招募"时，需要多次点击才能提交
 */
class RecruitDecisionProtection {
    constructor(options = {}) {
        this.decisionSelector = options.decisionSelector || 'select';
        this.submitSelector = options.submitSelector || 'button[type="submit"]';
        this.negativeValue = options.negativeValue || '不招募';
        this.formSelector = options.formSelector || 'form';

        this.requiredClicks = 0;
        this.currentClicks = 0;
        this.isEnabled = false;

        this.init();
    }

    init() {
        const decisionSelect = document.querySelector(this.decisionSelector);
        const submitBtn = document.querySelector(this.submitSelector);
        const form = document.querySelector(this.formSelector);

        if (!decisionSelect || !submitBtn || !form) {
            console.error('RecruitDecisionProtection: 找不到必要的元素');
            return;
        }

        // 监听决策选择变化
        decisionSelect.addEventListener('change', () => {
            this.handleDecisionChange(decisionSelect.value);
        });

        // 将实例暴露到全局，供现有的表单提交逻辑调用
        window.recruitDecisionProtection = this;
    }

    // 检查是否应该阻止提交
    shouldBlockSubmit() {
        return this.isEnabled && this.currentClicks < this.requiredClicks;
    }

    // 处理点击
    handleClick() {
        const submitBtn = document.querySelector(this.submitSelector);
        this.currentClicks++;

        // 添加打击感动效
        this.addImpactEffect(submitBtn);

        if (this.currentClicks >= this.requiredClicks) {
            // 达到点击次数，禁用防呆功能并允许提交
            this.isEnabled = false;
            this.updateSubmitButton(submitBtn);
        } else {
            // 更新按钮文本
            this.updateSubmitButton(submitBtn);
        }
    }

    handleDecisionChange(value) {
        const submitBtn = document.querySelector(this.submitSelector);

        if (value === this.negativeValue) {
            this.enableProtection(submitBtn);
        } else {
            this.disableProtection(submitBtn);
        }
    }

    enableProtection(submitBtn) {
        this.isEnabled = true;
        this.requiredClicks = this.getRandomClickCount();
        this.currentClicks = 0;
        this.updateSubmitButton(submitBtn);
    }

    disableProtection(submitBtn) {
        this.isEnabled = false;
        this.requiredClicks = 0;
        this.currentClicks = 0;
        submitBtn.textContent = '确认决策';
        submitBtn.disabled = false;
        submitBtn.classList.remove('btn-danger', 'btn-shake');
        submitBtn.classList.add('btn-primary');
    }

    getRandomClickCount() {
        // 返回18-38之间的随机数
        return Math.floor(Math.random() * (38 - 18 + 1)) + 18;
    }

    updateSubmitButton(submitBtn) {
        const remaining = this.requiredClicks - this.currentClicks;

        // 清除所有状态类
        submitBtn.classList.remove('btn-urgent', 'btn-complete', 'btn-counting');

        if (remaining <= 0) {
            submitBtn.textContent = '确定不招募？点击提交';
            submitBtn.disabled = false;
            submitBtn.classList.remove('btn-danger');
            submitBtn.classList.add('btn-primary', 'btn-complete');
        } else {
            submitBtn.textContent = `确定不招募？再点${remaining}次`;
            submitBtn.disabled = false;
            submitBtn.classList.remove('btn-primary');
            submitBtn.classList.add('btn-danger');

            // 剩余次数少于5次时添加紧急效果
            if (remaining <= 5) {
                submitBtn.classList.add('btn-urgent');
            }

            // 添加数字变化动画
            submitBtn.classList.add('btn-counting');
        }
    }

    
    addImpactEffect(element) {
        // 移除之前的动画类
        element.classList.remove('btn-shake', 'btn-pulse', 'btn-glow');

        // 强制重绘以确保动画重新开始
        void element.offsetWidth;

        // 根据当前进度选择不同的动画效果
        const progress = this.currentClicks / this.requiredClicks;

        if (progress < 0.3) {
            // 前期：简单震动
            element.classList.add('btn-shake');
        } else if (progress < 0.7) {
            // 中期：震动 + 脉冲
            element.classList.add('btn-shake', 'btn-pulse');
        } else {
            // 后期：震动 + 脉冲 + 发光 + 屏幕震动
            element.classList.add('btn-shake', 'btn-pulse', 'btn-glow');
            this.addScreenShake();
        }

        // 动画结束后移除类
        setTimeout(() => {
            element.classList.remove('btn-shake', 'btn-pulse', 'btn-glow');
        }, 600);

        // 添加粒子效果（如果支持）
        this.createParticleEffect(element);
    }

    addScreenShake() {
        // 添加屏幕震动效果
        document.body.classList.add('screen-shake');
        setTimeout(() => {
            document.body.classList.remove('screen-shake');
        }, 300);
    }

    createParticleEffect(element) {
        const rect = element.getBoundingClientRect();
        const particles = 8;

        for (let i = 0; i < particles; i++) {
            const particle = document.createElement('div');
            particle.className = 'impact-particle';
            particle.style.cssText = `
                position: fixed;
                left: ${rect.left + rect.width / 2}px;
                top: ${rect.top + rect.height / 2}px;
                width: 4px;
                height: 4px;
                background: ${this.getRandomColor()};
                border-radius: 50%;
                pointer-events: none;
                z-index: 9999;
                animation: particle-float 1s ease-out forwards;
                --angle: ${(360 / particles) * i}deg;
                --distance: ${30 + Math.random() * 20}px;
            `;

            document.body.appendChild(particle);

            // 动画结束后移除粒子
            setTimeout(() => {
                if (particle.parentNode) {
                    particle.parentNode.removeChild(particle);
                }
            }, 1000);
        }
    }

    getRandomColor() {
        const colors = [
            '#ff6b6b', '#4ecdc4', '#45b7d1', '#96ceb4',
            '#ffeaa7', '#fd79a8', '#a29bfe', '#6c5ce7'
        ];
        return colors[Math.floor(Math.random() * colors.length)];
    }
}

// 将类添加到全局作用域
window.RecruitDecisionProtection = RecruitDecisionProtection;