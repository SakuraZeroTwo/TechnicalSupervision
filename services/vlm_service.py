import os
import base64
from openai import OpenAI

# -------------------------------------------------------------------------
# 使用 OpenAI SDK 兼容模式
# -------------------------------------------------------------------------

try:
    # 初始化 OpenAI 客户端，指向阿里云的兼容 API
    client = OpenAI(
        api_key=os.getenv("ALIYUN_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
except TypeError:
    print("无法初始化 OpenAI 客户端。请检查 .env 文件中是否已设置 ALIYUN_API_KEY。")
    client = None

def encode_image_to_base64(image_path: str) -> str:
    """将图片文件编码为 Base64 字符串。"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def get_vlm_analysis(prompt_text: str, image_path: str) -> dict:
    """
    调用 qwen-vl-max 模型获取对图片和文本的分析
    使用 OpenAI SDK 兼容模式

    Args:
        prompt_text: 用户的输入文本描述
        image_path: 用户上传的图片文件路径

    Returns:
        模型的响应结果 (JSON) 或包含错误的字典。
    """
    if not client:
        return {"error": "OpenAI 客户端未初始化。"}

    # 1. 将图片编码为 Base64
    try:
        base64_image = encode_image_to_base64(image_path)
    except FileNotFoundError:
        return {"error": f"图片文件未找到: {image_path}"}
    except Exception as e:
        return {"error": f"图片编码失败: {e}"}

    # 2. 构建消息体 (messages)
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        # 根据图片格式动态设置 MIME 类型，这里以 jpeg 为例
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                },
                {
                    "type": "text",
                    "text": prompt_text
                }
            ]
        }
    ]

    # 3. 调用 API
    try:
        completion = client.chat.completions.create(
            model="qwen-vl-max",
            messages=messages,
            # temperature、top_p 等参数可以根据需要调整
        )
        # 提取模型返回的核心内容
        content = completion.choices[0].message.content
        # 期望返回的是 JSON 字符串，所以直接返回
        return {"content": content}

    except Exception as e:
        print(f"调用 VLM API 时发生错误: {e}")
        return {"error": str(e)}
    # """临时返回模拟数据用于测试"""
    # mock_response = {
    #     "content": """{
    #             "status_description": "设备绝缘子表面存在明显污闪痕迹，属于严重状态",
    #             "cause_analysis": "长期暴露在污染环境中，表面积累污垢导致闪络",
    #             "regulations": "按照DL/T 596-2021《电力设备预防性试验规程》相关要求处理",
    #             "supervision_suggestion": "立即停用设备，清洁绝缘子表面，进行绝缘测试",
    #             "entities": ["绝缘子", "污闪", "闪络"]
    #         }"""
    # }
    # return mock_response
