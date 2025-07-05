import os
import base64
from openai import OpenAI
from .file_service import file_service
import json
KNOWN_ENTITIES_STR = file_service.known_entities_str
# -------------------------------------------------------------------------
# 使用 OpenAI SDK 兼容模式
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

def encode_image_to_base64(image_path: str) -> str:
    """将图片文件编码为 Base64 字符串。"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

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

    1.  **状态描述 (status_description)**: 详细描述{'' if image_path else '根据描述推测'}设备的状态，并判断其严重程度（例如：一般、严重、紧急）。
    2.  **原因分析 (cause_analysis)**: 分析可能导致该问题的多种潜在原因。
    3.  **阶段识别 (stage)**: {f'问题属于用户指定的"{stage}"阶段' if stage else '从"规划可研阶段、工程设计阶段、设备采购阶段、设备制造阶段、设备验收阶段、设备安装阶段、设备调试阶段、竣工验收阶段、运维检修阶段、退役报废阶段"中，识别该问题最可能出现的阶段。'}
    4.  **监督意见 (supervision_suggestion)**: 提出具体、可执行的处理建议或监督意见。

    {'''
    5.  **实体提取 (entities)**: 从用户描述和你的分析中，识别出核心实体。请遵循以下规则：
        - **规则1**: 请优先从以下 '已知实体列表' 中进行识别，若出现已知实体列表内的设备或现象，直接识别，尽可能匹配上已知实体列表，如“主变压器”识别成“变压器”，出现列表内描述的现象也识别成现象实体。
        - **规则2**: 请识别通用设备名称或故障现象（如 '变压器', '局部放电'），而不是具体的、详细的设备型号（例如 'S11-M-100/10'）。
        - **已知实体列表**: [{KNOWN_ENTITIES_STR}]
        - 你的输出必须是一个标准的Python列表格式，例如 ["绝缘子", "污闪", "裂纹"]。
    '''  
    }

    请严格将你的回答以一个完整的 JSON 对象的格式返回，确保不包含任何额外的解释性文字。JSON对象必须包含以下键：'status_description', 'cause_analysis', 'stage', 'supervision_suggestion', 'entities'。

    用户描述: "{prompt_text}"
    """
    messages = []

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

    # 3. 调用 API
    try:
        completion = client.chat.completions.create(
            model="qwen-vl-max",
            messages=messages,
            temperature=0.2 # 稍低的温度确保分析的稳定性
        )
        # 提取模型返回的核心内容
        content = completion.choices[0].message.content
        # 期望返回的是 JSON 字符串，所以直接返回
        return {"content": content}

    except Exception as e:
        print(f"调用 VLM API 时发生错误: {e}")
        return {"error": str(e)}

# vvvvvvvv 【新增的独立实体识别函数】 vvvvvvvv
def get_vlm_entities(prompt_text: str) -> list:
    """
    【优化版】
    调用 qwen-vl-max 模型，专门用于从文本中提取实体。

    Args:
        prompt_text: 用户的输入文本描述。

    Returns:
        一个包含实体字符串的 Python 列表，例如 ["绝缘子", "裂纹"]。
        如果失败则返回空列表。
    """
    if not client:
        print("错误: VLM客户端未初始化。")
        return []

    # 【优化版】专门为实体识别设计的、更简洁的提示词
    entity_prompt = f"""
    你是一个专业的电力领域命名实体识别（NER）工具。你的任务是从用户描述中，识别出所有符合以下规则的设备实体或故障现象实体。

    **识别规则**:
    1.  **优先匹配**: 请优先从 '已知实体列表' 中进行识别和匹配。
    2.  **泛化识别**: 请识别通用名称（如 '变压器'），而不是具体型号。
    3.  **已知实体列表**: [{KNOWN_ENTITIES_STR}]

    ---
    **【优化点2: 增加一个完整的示例】**
    下面是一个处理示例，请严格模仿它的行为：
    [输入示例]
    用户描述: "检查发现主变压器出现异响，怀疑是内部有局部放电，而且套管上有明显裂纹，需要立即处理。"
    [输出示例]
    ["变压器", "异响", "局部放电", "套管", "裂纹"]
    **输出格式要求**:
    你的输出必须是一个标准的、可以直接用 `json.loads` 解析的Python列表格式的JSON字符串。
    绝对不要包含任何额外的解释性文字、Markdown标记或 "输出示例" 这个词本身。
    现在，请处理以下真实的用户描述，并返回所有识别出的实体
    请注意，”主变压器““主变”等类似的实体列表中有但表述略有不同的应该直接识别为列表内实体：

    [真实输入]
    用户描述: "{prompt_text}"
    """

    messages = [{"role": "user", "content": entity_prompt}]

    try:
        completion = client.chat.completions.create(
            model="qwen-vl-max",
            messages=messages,
            # 【优化点3: 适当提高温度，鼓励模型识别更多可能实体】
            temperature=0.1
        )
        content = completion.choices[0].message.content

        # 清理并解析JSON
        start_index = content.find('[')
        end_index = content.rfind(']')
        if start_index != -1 and end_index != -1:
            json_string = content[start_index:end_index + 1]
            # 去除可能存在的重复项
            entities = json.loads(json_string)
            return list(dict.fromkeys(entities))  # 用字典去重并保持顺序
        else:
            print(f"警告: VLM未能返回有效的列表格式。原始返回: {content}")
            return []

    except json.JSONDecodeError as e:
        print(f"解析VLM实体识别结果失败: {e}")
        print(f"原始返回内容: {content}")
        return []
    except Exception as e:
        print(f"调用 VLM API 进行实体识别时发生错误: {e}")
        return []