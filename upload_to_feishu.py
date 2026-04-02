#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书文件上传工具
"""
import os
import requests
import json

# 飞书配置
FEISHU_APP_ID = 'cli_a9465807bdb61cb6'
FEISHU_APP_SECRET = '9HhxRANlakGT6o11dBXuzhQEchKHCXmY'
FEISHU_OPEN_ID = 'ou_02a3ba04fd1f1aa830b270ec34752b25'  # 接收者 open_id

def get_tenant_access_token():
    """获取 tenant_access_token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json"}
    data = {
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET
    }
    response = requests.post(url, headers=headers, json=data)
    result = response.json()
    if result.get('code') == 0:
        return result['tenant_access_token']
    else:
        raise Exception(f"获取token失败: {result}")

def upload_file(token, file_path):
    """上传文件到飞书"""
    url = "https://open.feishu.cn/open-apis/im/v1/files"
    headers = {"Authorization": f"Bearer {token}"}
    
    with open(file_path, 'rb') as f:
        files = {
            'file': (os.path.basename(file_path), f, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        }
        data = {'file_type': 'stream'}
        response = requests.post(url, headers=headers, files=files, data=data)
    
    result = response.json()
    if result.get('code') == 0:
        return result['data']['file_key']
    else:
        raise Exception(f"上传文件失败: {result}")

def send_file_message(token, open_id, file_key):
    """发送文件消息到用户"""
    url = "https://open.feishu.cn/open-apis/im/v1/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    params = {"receive_id_type": "open_id"}
    data = {
        "receive_id": open_id,
        "msg_type": "file",
        "content": json.dumps({"file_key": file_key})
    }
    
    response = requests.post(url, headers=headers, params=params, json=data)
    result = response.json()
    if result.get('code') == 0:
        return result['data']['message_id']
    else:
        raise Exception(f"发送消息失败: {result}")

def main():
    file_path = "chapter3_new_v2.docx"
    
    if not os.path.exists(file_path):
        print(f"文件不存在: {file_path}")
        return
    
    print("1. 获取访问令牌...")
    token = get_tenant_access_token()
    
    print("2. 上传文件...")
    file_key = upload_file(token, file_path)
    print(f"   文件已上传，file_key: {file_key}")
    
    print("3. 发送到用户...")
    message_id = send_file_message(token, FEISHU_OPEN_ID, file_key)
    print(f"   消息已发送，message_id: {message_id}")
    print("   文件发送成功！")

if __name__ == '__main__':
    main()
