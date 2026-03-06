"""
飞书API客户端
"""
import json
import time
import hashlib
import base64
import hmac
import requests
from typing import Optional, Dict, Any, List


class FeishuClient:
    """飞书开放平台API客户端"""

    BASE_URL = "https://open.feishu.cn/open-apis"

    def __init__(self, app_id: str, app_secret: str):
        """
        初始化飞书客户端

        Args:
            app_id: 飞书应用的App ID
            app_secret: 飞书应用的App Secret
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self._tenant_access_token = None
        self._token_expires_at = 0

    def get_tenant_access_token(self) -> str:
        """
        获取tenant_access_token

        Returns:
            tenant_access_token字符串

        Raises:
            requests.RequestException: API请求失败
        """
        # 如果token还有效，直接返回
        if self._tenant_access_token and time.time() < self._token_expires_at:
            return self._tenant_access_token

        url = f"{self.BASE_URL}/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }

        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()

        data = response.json()
        if data.get("code") != 0:
            raise Exception(f"获取tenant_access_token失败: {data.get('msg')}")

        self._tenant_access_token = data["tenant_access_token"]
        # 提前5分钟过期，留出缓冲时间
        self._token_expires_at = time.time() + data.get("expire", 7200) - 300

        return self._tenant_access_token

    def _get_headers(self) -> Dict[str, str]:
        """获取API请求头"""
        token = self.get_tenant_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }

    def get_document_content(self, doc_token: str) -> Dict[str, Any]:
        """
        获取飞书文档纯文本内容

        Args:
            doc_token: 文档的document_id

        Returns:
            文档内容字典，包含纯文本content字段

        Raises:
            requests.RequestException: API请求失败
        """
        url = f"{self.BASE_URL}/docx/v1/documents/{doc_token}/raw_content"
        headers = self._get_headers()

        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        if data.get("code") != 0:
            raise Exception(f"获取文档内容失败: {data.get('msg')}")

        # 返回包含纯文本内容的数据
        return data.get("data", {})

    def get_folder_meta(self, folder_token: str) -> Dict[str, Any]:
        """
        获取文件夹元数据

        Args:
            folder_token: 文件夹token

        Returns:
            文件夹元数据JSON，包含name, token等
        """
        url = f"{self.BASE_URL}/drive/explorer/v2/folder/{folder_token}/meta"
        headers = self._get_headers()

        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        if data.get("code") != 0:
            raise Exception(f"获取文件夹元数据失败: {data.get('msg')}")

        return data.get("data", {})

    def get_folder_files(self, folder_token: str = "", page_size: int = 100, page_token: str = "") -> Dict[str, Any]:
        """
        获取文件夹中的文件清单

        Args:
            folder_token: 文件夹token，空字符串表示根目录
            page_size: 每页数量
            page_token: 分页标记

        Returns:
            文件列表
        """
        url = f"{self.BASE_URL}/drive/v1/files"
        headers = self._get_headers()

        params = {"page_size": page_size}
        if folder_token:
            params["folder_token"] = folder_token
        if page_token:
            params["page_token"] = page_token

        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()
        if data.get("code") != 0:
            raise Exception(f"获取文件夹文件失败: {data.get('msg')}")

        return data.get("data", {})

    def get_document_info(self, doc_token: str) -> Dict[str, Any]:
        """
        获取飞书文档基本信息

        Args:
            doc_token: 文档的document_id

        Returns:
            文档信息JSON

        Raises:
            requests.RequestException: API请求失败
        """
        url = f"{self.BASE_URL}/docx/v1/documents/{doc_token}"
        headers = self._get_headers()

        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        if data.get("code") != 0:
            raise Exception(f"获取文档信息失败: {data.get('msg')}")

        doc_data = data.get("data", {})

        # 转换格式以保持与之前一致的接口
        return {
            "token": doc_token,
            "name": doc_data.get("title", ""),
            "type": "doc",
            "created_time": doc_data.get("created_time", ""),
            "updated_time": doc_data.get("updated_time", "")
        }

    def send_message(
        self,
        receive_id: str,
        msg_type: str = "text",
        content: Optional[Dict[str, Any]] = None,
        receive_id_type: str = "open_id"
    ) -> Dict[str, Any]:
        """
        发送消息

        Args:
            receive_id: 接收者ID
            msg_type: 消息类型 (text, post, interactive)
            content: 消息内容
            receive_id_type: 接收者ID类型 (open_id, user_id, union_id, email, chat_id)

        Returns:
            发送结果

        Raises:
            requests.RequestException: API请求失败
        """
        url = f"{self.BASE_URL}/im/v1/messages/{receive_id_type}/{receive_id}"
        headers = self._get_headers()

        payload = {
            "msg_type": msg_type,
            "content": json.dumps(content) if content else json.dumps({"text": ""})
        }

        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        if data.get("code") != 0:
            raise Exception(f"发送消息失败: {data.get('msg')}")

        return data

    def send_text_message(self, receive_id: str, text: str, receive_id_type: str = "open_id") -> Dict[str, Any]:
        """发送文本消息"""
        return self.send_message(
            receive_id=receive_id,
            msg_type="text",
            content={"text": text},
            receive_id_type=receive_id_type
        )

    def send_interactive_card(
        self,
        receive_id: str,
        card_template: str,
        variables: Optional[Dict[str, Any]] = None,
        receive_id_type: str = "open_id"
    ) -> Dict[str, Any]:
        """发送卡片消息"""
        content = {"template": card_template}
        if variables:
            content["variables"] = variables

        return self.send_message(
            receive_id=receive_id,
            msg_type="interactive",
            content=content,
            receive_id_type=receive_id_type
        )

    def reply_message(self, message_id: str, msg_type: str = "text", content: Optional[Dict] = None) -> Dict[str, Any]:
        """
        回复消息

        Args:
            message_id: 消息ID
            msg_type: 消息类型
            content: 消息内容

        Returns:
            回复结果
        """
        url = f"{self.BASE_URL}/im/v1/messages/{message_id}/reply"
        headers = self._get_headers()

        payload = {
            "msg_type": msg_type,
            "content": json.dumps(content) if content else json.dumps({"text": ""})
        }

        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        if data.get("code") != 0:
            raise Exception(f"回复消息失败: {data.get('msg')}")

        return data

    def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """
        获取用户信息

        Args:
            user_id: 用户ID

        Returns:
            用户信息
        """
        url = f"{self.BASE_URL}/contact/v3/users/{user_id}"
        headers = self._get_headers()

        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()
        if data.get("code") != 0:
            raise Exception(f"获取用户信息失败: {data.get('msg')}")

        return data.get("data", {})

    def verify_webhook_signature(
        self,
        timestamp: str,
        nonce: str,
        signature: str,
        encrypt_key: str
    ) -> bool:
        """
        验证飞书回调签名

        Args:
            timestamp: 时间戳
            nonce: 随机字符串
            signature: 签名
            encrypt_key: 加密密钥

        Returns:
            签名是否有效
        """
        if not encrypt_key:
            return True

        # 构建签名字符串
        sign_str = f"{timestamp}{nonce}{encrypt_key}"
        sign_bytes = sign_str.encode("utf-8")

        # 使用hmac-sha256计算签名
        hm = hmac.new(
            encrypt_key.encode("utf-8"),
            sign_bytes,
            hashlib.sha256
        )
        computed_signature = base64.b64encode(hm.digest()).decode("utf-8")

        return computed_signature == signature

    @staticmethod
    def decrypt_content(encrypt_key: str, encrypted_content: str) -> str:
        """
        解密内容

        Args:
            encrypt_key: 加密密钥
            encrypted_content: 加密内容

        Returns:
            解密后的内容
        """
        if not encrypted_content:
            return ""

        try:
            # Base64解码
            encrypted_bytes = base64.b64decode(encrypted_content)
            # 密钥转换为bytes
            key_bytes = encrypt_key.encode("utf-8")
            # 补齐密钥到32字节
            if len(key_bytes) < 32:
                key_bytes = key_bytes + b'\0' * (32 - len(key_bytes))
            elif len(key_bytes) > 32:
                key_bytes = key_bytes[:32]

            # AES解密 (这里简化处理，实际需要使用cryptography库)
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.backends import default_backend

            # 提取IV (前16字节)
            iv = encrypted_bytes[:16]
            # 提取密文 (去除IV后的部分)
            ciphertext = encrypted_bytes[16:]

            cipher = Cipher(
                algorithms.AES(key_bytes),
                modes.CBC(iv),
                backend=default_backend()
            )
            decryptor = cipher.decryptor()
            padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()

            # 去除PKCS7填充
            padding_length = padded_plaintext[-1]
            plaintext = padded_plaintext[:-padding_length]

            return plaintext.decode("utf-8")
        except Exception as e:
            raise Exception(f"解密失败: {str(e)}")


def create_client(app_id: str, app_secret: str) -> FeishuClient:
    """创建飞书客户端的工厂函数"""
    return FeishuClient(app_id, app_secret)
