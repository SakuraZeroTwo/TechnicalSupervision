import os
import base64
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


API_KEY = os.getenv("ALIYUN_API_KEY")
MODEL_NAME = "qwen-vl-max"
ALIYUN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

def encode_image_to_base64(image_path):
    """
    将图片文件编码为Base64字符串。
    """
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except Exception as e:
        print(f"图片编码失败: {e}")
        return None

def get_vlm_analysis(prompt: str, image_path: str):
    """
    调用阿里云通义千问VLM模型进行多模态分析。

    Args:
        prompt (str): 发送给模型的指令性文本。
        image_path (str): 需要分析的本地图片路径。

    Returns:
        dict: 包含模型分析结果的字典。
    """
    if not API_KEY:
        raise ValueError("未找到环境变量 ALIYUN_API_KEY，请检查 .env 文件。")

    # 1. 初始化OpenAI客户端，指向阿里云的API服务地址
    client = OpenAI(
        api_key=API_KEY,
        base_url=ALIYUN_BASE_URL,
    )

    # 2. 将图片编码为Base64
    base64_image = encode_image_to_base64(image_path)
    if not base64_image:
        return {"error": "无法编码图片"}

    # 3. 构建发送给API的消息体
    messages = [
        {
            "role": "system",
            "content": [{"type": "text", "text": "You are a helpful assistant."}]
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        # 使用 f-string 直接嵌入 base64 编码
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                },
                {
                    "type": "text",
                    "text": prompt
                }
            ]
        }
    ]

    try:
        # 4. 发起API调用
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages
        )
        # 5. 提取并返回模型生成的文本内容
        content = completion.choices[0].message.content
        return {"content": content}

    except Exception as e:
        print(f"调用VLM模型API时发生错误: {e}")
        # 在出错时可以返回一个包含错误信息的字典
        return {"error": f"API call failed: {str(e)}"}