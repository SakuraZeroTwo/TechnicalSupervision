import os
import base64
from openai import OpenAI
from .file_service import file_service

# -------------------------------------------------------------------------
# 【第一处修改】从 file_service 获取预加载的实体库字符串
# -------------------------------------------------------------------------
KNOWN_ENTITIES_STR = file_service.known_entities_str

# -------------------------------------------------------------------------
# 使用 OpenAI SDK 兼容模式 (这部分与您的代码完全相同)
# -------------------------------------------------------------------------
try:
    # 初始化 OpenAI 客户端，指向阿里云的兼容 API
    client = OpenAI(
        api_key=os.getenv("ALIYUN_API_KEY"),
        # 【已修正】移除了 base_url 周围多余的 Markdown 链接格式
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
except TypeError:
    print("无法初始化 OpenAI 客户端。请检查 .env 文件中是否已设置 ALIYUN_API_KEY。")
    client = None


# (这个函数与您的代码完全相同)
def encode_image_to_base64(image_path: str) -> str:
    """将图片文件编码为 Base64 字符串。"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


# (这个函数的主体与您的代码完全相同，除了 prompt 里的第6点)
def get_vlm_analysis(prompt_text: str, image_path: str = None, stage: str = None) -> dict:
    """
    调用 qwen-vl-max 模型获取对图片和文本的分析
    使用 OpenAI SDK 兼容模式

    Args:
        prompt_text: 用户的输入文本描述
        image_path: 用户上传的图片文件路径（可选）
        stage: 问题阶段（如规划可研等）

    Returns:
        模型的响应结果 (JSON) 或包含错误的字典。
    """
    if not client:
        return {"error": "OpenAI 客户端未初始化。"}

    # 提示词
    enhanced_prompt = f"""
    你是一个资深的电力设备巡检专家。请根据以下用户描述{'' if image_path else '(无图片提供)'}，完成以下分析任务：

    1.  **扩写描述 (enhanced_description)**: 根据{'' if image_path else '用户'}描述，用专业的语言对问题进行详细、全面的扩写。
    2.  **状态描述 (status_description)**: 详细描述{'' if image_path else '根据描述推测'}设备的状态，并判断其严重程度（例如：一般、严重、紧急）。
    3.  **原因分析 (cause_analysis)**: 分析可能导致该问题的多种潜在原因。
    4.  **阶段识别 (stage)**: {f'问题属于用户指定的"{stage}"阶段' if stage else '从"规划可研阶段、工程设计阶段、设备采购阶段、设备制造阶段、设备验收阶段、设备安装阶段、设备调试阶段、竣工验收阶段、运维检修阶段、退役报废阶段"中，识别该问题最可能出现的阶段。'}
    5.  **监督意见 (supervision_suggestion)**: 提出具体、可执行的处理建议或监督意见。

    {'''
    6.  **实体提取 (entities)**: 从用户描述和你的分析中，识别出核心实体。请遵循以下规则：
        - **规则1**: 请优先从以下 '已知实体列表' 中进行识别。
        - **规则2**: 请识别通用设备名称或故障现象（如 '变压器', '局部放电'），而不是具体的、详细的设备型号（例如 'S11-M-100/10'）。
        - **已知实体列表**: [{KNOWN_ENTITIES_STR}]
        - 你的输出必须是一个标准的Python列表格式，例如 ["绝缘子", "污闪", "裂纹"]。
    '''  
    }

    请严格将你的回答以一个完整的 JSON 对象的格式返回，确保不包含任何额外的解释性文字。JSON对象必须包含以下键：'enhanced_description', 'status_description', 'cause_analysis', 'stage', 'supervision_suggestion', 'entities'。

    用户描述: "{prompt_text}"
    """
    messages = []

    # (这部分与您的代码完全相同)
    # 有图片时添加图片消息
    if image_path:
        try:
            base64_image = encode_image_to_base64(image_path)
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
        except FileNotFoundError:
            return {"error": f"图片文件未找到: {image_path}"}
        except Exception as e:
            return {"error": f"图片编码失败: {e}"}
    else:
        # 无图片时只发送文本
        messages = [
            {
                "role": "user",
                "content": enhanced_prompt
            }
        ]

    # (这部分与您的代码完全相同)
    # 3. 调用 API
    try:
        completion = client.chat.completions.create(
            model="qwen-vl-max",
            messages=messages,
            temperature=0.2  # 稍低的温度确保分析的稳定性
        )
        # 提取模型返回的核心内容
        content = completion.choices[0].message.content
        # 期望返回的是 JSON 字符串，所以直接返回
        return {"content": content}

    except Exception as e:
        print(f"调用 VLM API 时发生错误: {e}")
        return {"error": str(e)}