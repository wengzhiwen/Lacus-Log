#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试主播管理筛选器持久化功能
"""

import requests
import json

def test_filter_persistence():
    """测试筛选器持久化功能"""
    base_url = "http://localhost:5000"
    
    # 模拟登录（需要根据实际情况调整）
    session = requests.Session()
    
    print("=== 测试主播管理筛选器持久化功能 ===")
    
    # 1. 测试设置筛选器
    print("\n1. 设置筛选器参数...")
    filter_params = {
        'rank': '正式主播',
        'status': '已招募',
        'owner_id': '1',
        'q': '测试搜索'
    }
    
    # 调用 options API 来持久化筛选器
    options_url = f"{base_url}/api/pilots/options"
    response = session.get(options_url, params=filter_params)
    
    if response.status_code == 200:
        result = response.json()
        print(f"✓ Options API 调用成功")
        print(f"  返回的筛选器状态: {result.get('data', {}).get('current_filters', {})}")
    else:
        print(f"✗ Options API 调用失败: {response.status_code}")
        print(f"  错误信息: {response.text}")
        return
    
    # 2. 测试获取筛选器状态
    print("\n2. 获取筛选器状态...")
    response2 = session.get(options_url)
    
    if response2.status_code == 200:
        result2 = response2.json()
        current_filters = result2.get('data', {}).get('current_filters', {})
        print(f"✓ 筛选器状态获取成功")
        print(f"  当前筛选器状态: {current_filters}")
        
        # 检查筛选器是否正确持久化
        if current_filters.get('rank') == '正式主播':
            print("✓ 主播分类筛选器持久化成功")
        else:
            print(f"✗ 主播分类筛选器持久化失败，期望: 正式主播，实际: {current_filters.get('rank')}")
            
        if current_filters.get('status') == '已招募':
            print("✓ 状态筛选器持久化成功")
        else:
            print(f"✗ 状态筛选器持久化失败，期望: 已招募，实际: {current_filters.get('status')}")
            
        if current_filters.get('owner_id') == '1':
            print("✓ 直属运营筛选器持久化成功")
        else:
            print(f"✗ 直属运营筛选器持久化失败，期望: 1，实际: {current_filters.get('owner_id')}")
            
        if current_filters.get('q') == '测试搜索':
            print("✓ 搜索词筛选器持久化成功")
        else:
            print(f"✗ 搜索词筛选器持久化失败，期望: 测试搜索，实际: {current_filters.get('q')}")
    else:
        print(f"✗ 筛选器状态获取失败: {response2.status_code}")
        print(f"  错误信息: {response2.text}")

if __name__ == "__main__":
    test_filter_persistence()
