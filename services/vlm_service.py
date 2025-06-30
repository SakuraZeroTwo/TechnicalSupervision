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

def get_vlm_analysis(prompt_text: str, image_path: str, stage: str = None) -> dict:
    """
    调用 qwen-vl-max 模型获取对图片和文本的分析
    使用 OpenAI SDK 兼容模式

    Args:
        prompt_text: 用户的输入文本描述
        image_path: 用户上传的图片文件路径
        stage: 问题阶段（如规划可研、设计等）

    Returns:
        模型的响应结果 (JSON) 或包含错误的字典。
    """
    if not client:
        return {"error": "OpenAI 客户端未初始化。"}

    enhanced_prompt = f"""
    你是一个资深的电力设备巡检专家。请根据以下用户描述和图片，完成以下分析任务：

    1. **扩写描述**: 根据图片扩写用户描述，使描述更加专业、全面。
    2. **状态描述**: 详细描述设备的状态，判断严重程度（例如：一般、严重）。
    3. **原因分析**: 分析可能导致该问题的潜在原因。
    4. **阶段识别**: {f'问题属于用户指定的"{stage}"阶段' if stage else '识别该问题可能出现的阶段（如规划可研阶段、设计阶段、安装调试阶段、运行维护阶段等）'}。
    5. **相关条例**: 可能关联的电力技术监督条例或安全规程编号（例如：DL/T 596-2021）。
    6. **监督意见**: 提出具体的处理建议或监督意见。
    7. **实体提取**: 识别描述和图片中的核心实体（设备名称、问题类型、部件等），以便后续检索相关文档。

    请将你的回答以 JSON 格式返回，包含以下键：'enhanced_description', 'status_description', 'cause_analysis', 'stage', 'regulations', 'supervision_suggestion', 'entities'。

    用户描述: "{prompt_text}"
    """
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
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                },
                {
                    "type": "text",
                    "text": enhanced_prompt
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
