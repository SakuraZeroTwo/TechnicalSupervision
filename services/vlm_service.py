import os
import base64
from openai import OpenAI
from .file_service import file_service
import re
import json

KNOWN_ENTITIES_STR = file_service.known_entities_str
# -------------------------------------------------------------------------
# 使用 OpenAI SDK 兼容模式
# -------------------------------------------------------------------------

try:
    # 初始化 OpenAI 客户端，指向阿里云的兼容 API
    client = OpenAI(
        api_key=os.getenv("ALIYUN_API_KEY"),
        # api_key="dummy",
        # 【已修正】移除了 base_url 周围多余的 Markdown 链接格式
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        # base_url="http://localhost:9192/v1",
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

    1.  **扩写描述 (expanded_description)**: 基于用户提供的描述和图片（如有），请用专业、详细、书面的语言，对问题现象进行扩写，使其更适合作为正式报告中的问题描述。
    2.  **状态描述 (status_description)**: 详细描述{'' if image_path else '根据描述推测'}设备的状态，并判断其严重程度（例如：一般、严重、紧急）。
    3.  **原因分析 (cause_analysis)**: 分析可能导致该问题的多种潜在原因。
    4.  **阶段识别 (stage)**: {f'问题属于用户指定的"{stage}"阶段' if stage else '从"规划可研阶段、工程设计阶段、设备采购阶段、设备制造阶段、设备验收阶段、设备安装阶段、设备调试阶段、竣工验收阶段、运维检修阶段、退役报废阶段"中，识别该问题最可能出现的阶段。'}
    5.  **监督意见 (supervision_suggestion)**: 提出具体、可执行的处理建议或监督意见。

    {'''
    6.  **实体提取 (entities)**: 从用户描述和你的分析中，识别出核心实体。请遵循以下规则：
        - **规则1**: 请优先从以下 '已知实体列表' 中进行识别，若出现已知实体列表内的设备或现象，直接识别，尽可能匹配上已知实体列表，如“主变压器”识别成“变压器”，出现列表内描述的现象也识别成现象实体。
        - **规则2**: 请识别通用设备名称或故障现象（如 '变压器', '局部放电'），而不是具体的、详细的设备型号（例如 'S11-M-100/10'）。
        - **已知实体列表**: [{KNOWN_ENTITIES_STR}]
        - 你的输出必须是一个标准的Python列表格式，例如 ["绝缘子", "污闪", "裂纹"]。
    '''
    }

    请严格将你的回答以一个完整的 JSON 对象的格式返回，确保不包含任何额外的解释性文字。JSON对象必须包含以下键：'expanded_description'，'status_description', 'cause_analysis', 'stage', 'supervision_suggestion', 'entities'。

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
            # model="Qwen2.5-VL-7B-Instruct",
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
            # model="Qwen2.5-VL-7B-Instruct",
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

def rerank_regulations_with_vlm(description: str, regulations: list) -> list:
    """
    使用VLM对候选规范列表进行重排序。

    Args:
        description: 用户输入的问题描述。
        regulations: 从向量搜索中获得的候选规范列表。

    Returns:
        一个根据VLM评分排序后的规范列表。
    """
    if not regulations:
        return []

    # 1. 构建一个详细的提示，要求模型对每个规范进行评分
    prompt_parts = [f"你是一个电力技术监督专家。请根据以下问题描述，评估每一条技术监督规范的相关性，并按从0到100的相关性分数进行打分。请严格按照'【规范ID】: [分数]'的格式输出，每个规范一行。\n\n问题描述：\n---\n{description}\n---\n\n候选规范列表：\n"]
    for i, reg in enumerate(regulations):
        reg_text = f"标题: {reg.get('title', '')}\n监督依据: {reg.get('basis', '')}\n监督要点: {reg.get('points', '')}\n监督要求: {reg.get('requirements', '')}"
        prompt_parts.append(f"【规范{i}】:\n{reg_text}\n")

    full_prompt = "".join(prompt_parts)

    # 2. 调用VLM服务
    try:
        response = client.chat.completions.create(
            model="qwen-vl-max",
            # model="Qwen2.5-VL-7B-Instruct",
            messages=[{'role': 'user', 'content': full_prompt}],
            temperature=0.0, # 使用低温以获得更稳定的评分
        )
        content = response.choices[0].message.content
    except Exception as e:
        print(f"调用VLM进行重排时出错: {e}")
        # 如果VLM失败，则返回原始列表，避免整个流程失败
        return regulations

    # 3. 解析VLM的评分结果
    scores = {}
    # 正则表达式匹配 "【规范X】: Y" 或 "【规范X】：Y"
    score_matches = re.findall(r'【规范(\d+)】\s*[:：]\s*(\d+)', content)
    for reg_id, score in score_matches:
        try:
            scores[int(reg_id)] = int(score)
        except (ValueError, IndexError):
            continue

    # 4. 将分数附加到原始规范对象上，并处理未被评分的规范
    for i, reg in enumerate(regulations):
        # VLM评分的权重更高，向量搜索的原始分数作为次要排序依据
        reg['vlm_score'] = scores.get(i, 0) # 如果VLM没有评分，则默认为0
        reg['final_score'] = reg['vlm_score'] + reg.get('score', 0) * 0.1 # 组合分数

    # 5. 根据最终分数进行降序排序
    regulations.sort(key=lambda x: x.get('final_score', 0), reverse=True)

    return regulations
# import os
# import base64
# import requests
# import json
# from .file_service import file_service
# import re
#
# KNOWN_ENTITIES_STR = file_service.known_entities_str
#
# # -------------------------------------------------------------------------
# # 使用直接HTTP请求调用API
# # -------------------------------------------------------------------------
#
# # API配置
# API_BASE_URL = "http://localhost:9192/v1"
# API_KEY = "dummy"  # 如果需要的话
# MODEL_NAME = "Qwen2.5-VL-7B-Instruct"
#
# def encode_image_to_base64(image_path: str) -> str:
#     """将图片文件编码为 Base64 字符串。"""
#     with open(image_path, "rb") as image_file:
#         return base64.b64encode(image_file.read()).decode('utf-8')
#
# def call_vlm_api(messages: list, temperature: float = 0.2, max_tokens: int = None) -> dict:
#     """
#     直接调用VLM API的通用函数
#
#     Args:
#         messages: 消息列表
#         temperature: 温度参数
#
#     Returns:
#         API响应结果
#     """
#     headers = {
#         "Content-Type": "application/json",
#         "Authorization": f"Bearer {API_KEY}"
#     }
#
#     payload = {
#         "model": MODEL_NAME,
#         "messages": messages,
#         "temperature": temperature
#     }
#
#     if max_tokens is not None:
#         payload["max_tokens"] = max_tokens
#
#     try:
#         response = requests.post(
#             f"{API_BASE_URL}/chat/completions",
#             headers=headers,
#             json=payload,
#             timeout=120  # 2分钟超时
#         )
#         response.raise_for_status()
#         return response.json()
#     except requests.exceptions.RequestException as e:
#         raise Exception(f"API调用失败: {e}")
#
# def get_vlm_analysis(prompt_text: str, image_path: str = None, stage: str = None) -> dict:
#     """
#     调用VLM模型获取对图片和文本的分析
#
#     Args:
#         prompt_text: 用户的输入文本描述
#         image_path: 用户上传的图片文件路径（可选）
#         stage: 问题阶段（如规划可研等）
#
#     Returns:
#         模型的响应结果 (JSON) 或包含错误的字典。
#     """
#     # 提示词
#     enhanced_prompt = f"""
#     你是一个资深的电力设备巡检专家。请根据以下用户描述{'' if image_path else '(无图片提供)'}，完成以下分析任务：
#
#     1.  **扩写描述 (expanded_description)**: 基于用户提供的描述和图片（如有），请用专业、详细、书面的语言，对问题现象进行扩写，使其更适合作为正式报告中的问题描述。
#     2.  **状态描述 (status_description)**: 详细描述{'' if image_path else '根据描述推测'}设备的状态，并判断其严重程度（例如：一般、严重、紧急）。
#     3.  **原因分析 (cause_analysis)**: 分析可能导致该问题的多种潜在原因。
#     4.  **阶段识别 (stage)**: {f'问题属于用户指定的"{stage}"阶段' if stage else '从"规划可研阶段、工程设计阶段、设备采购阶段、设备制造阶段、设备验收阶段、设备安装阶段、设备调试阶段、竣工验收阶段、运维检修阶段、退役报废阶段"中，识别该问题最可能出现的阶段。'}
#     5.  **监督意见 (supervision_suggestion)**: 提出具体、可执行的处理建议或监督意见。
#
#     {'''
#     6.  **实体提取 (entities)**: 从用户描述和你的分析中，识别出核心实体。请遵循以下规则：
#         - **规则1**: 请优先从以下 '已知实体列表' 中进行识别，若出现已知实体列表内的设备或现象，直接识别，尽可能匹配上已知实体列表，如"主变压器"识别成"变压器"，出现列表内描述的现象也识别成现象实体。
#         - **规则2**: 请识别通用设备名称或故障现象（如 '变压器', '局部放电'），而不是具体的、详细的设备型号（例如 'S11-M-100/10'）。
#         - **已知实体列表**: [{KNOWN_ENTITIES_STR}]
#         - 你的输出必须是一个标准的Python列表格式，例如 ["绝缘子", "污闪", "裂纹"]。
#     '''
#     }
#
#     请严格将你的回答以一个完整的 JSON 对象的格式返回，确保不包含任何额外的解释性文字。JSON对象必须包含以下键：'expanded_description'，'status_description', 'cause_analysis', 'stage', 'supervision_suggestion', 'entities'。
#
#     用户描述: "{prompt_text}"
#     """
#
#     messages = []
#
#     # 有图片时添加图片消息
#     if image_path:
#         try:
#             base64_image = encode_image_to_base64(image_path)
#             messages = [
#                 {
#                     "role": "user",
#                     "content": [
#                         {
#                             "type": "image_url",
#                             "image_url": {
#                                 "url": f"data:image/jpeg;base64,{base64_image}"
#                             }
#                         },
#                         {
#                             "type": "text",
#                             "text": enhanced_prompt
#                         }
#                     ]
#                 }
#             ]
#         except FileNotFoundError:
#             return {"error": f"图片文件未找到: {image_path}"}
#         except Exception as e:
#             return {"error": f"图片编码失败: {e}"}
#     else:
#         # 无图片时只发送文本
#         messages = [
#             {
#                 "role": "user",
#                 "content": enhanced_prompt
#             }
#         ]
#
#     # 调用 API
#     try:
#         response = call_vlm_api(messages, temperature=0.2, max_tokens=None)
#         content = response['choices'][0]['message']['content']
#         return {"content": content}
#     except Exception as e:
#         print(f"调用 VLM API 时发生错误: {e}")
#         return {"error": str(e)}
#
# def get_vlm_entities(prompt_text: str) -> list:
#     """
#     调用VLM模型，专门用于从文本中提取实体。
#
#     Args:
#         prompt_text: 用户的输入文本描述。
#
#     Returns:
#         一个包含实体字符串的 Python 列表，例如 ["绝缘子", "裂纹"]。
#         如果失败则返回空列表。
#     """
#     # 专门为实体识别设计的提示词
#     entity_prompt = f"""
#     你是一个专业的电力领域命名实体识别（NER）工具。你的任务是从用户描述中，识别出所有符合以下规则的设备实体或故障现象实体。
#
#     **识别规则**:
#     1.  **优先匹配**: 请优先从 '已知实体列表' 中进行识别和匹配。
#     2.  **泛化识别**: 请识别通用名称（如 '变压器'），而不是具体型号。
#     3.  **已知实体列表**: [{KNOWN_ENTITIES_STR}]
#
#     ---
#     下面是一个处理示例，请严格模仿它的行为：
#     [输入示例]
#     用户描述: "检查发现主变压器出现异响，怀疑是内部有局部放电，而且套管上有明显裂纹，需要立即处理。"
#     [输出示例]
#     ["变压器", "异响", "局部放电", "套管", "裂纹"]
#     **输出格式要求**:
#     你的输出必须是一个标准的、可以直接用 `json.loads` 解析的Python列表格式的JSON字符串。
#     绝对不要包含任何额外的解释性文字、Markdown标记或 "输出示例" 这个词本身。
#     现在，请处理以下真实的用户描述，并返回所有识别出的实体
#     请注意，"主变压器""主变"等类似的实体列表中有但表述略有不同的应该直接识别为列表内实体：
#
#     [真实输入]
#     用户描述: "{prompt_text}"
#     """
#
#     messages = [{"role": "user", "content": entity_prompt}]
#
#     try:
#         response = call_vlm_api(messages, temperature=0.1, max_tokens=None)
#         content = response['choices'][0]['message']['content']
#
#         # 清理并解析JSON
#         start_index = content.find('[')
#         end_index = content.rfind(']')
#         if start_index != -1 and end_index != -1:
#             json_string = content[start_index:end_index + 1]
#             # 去除可能存在的重复项
#             entities = json.loads(json_string)
#             return list(dict.fromkeys(entities))  # 用字典去重并保持顺序
#         else:
#             print(f"警告: VLM未能返回有效的列表格式。原始返回: {content}")
#             return []
#
#     except json.JSONDecodeError as e:
#         print(f"解析VLM实体识别结果失败: {e}")
#         print(f"原始返回内容: {content}")
#         return []
#     except Exception as e:
#         print(f"调用 VLM API 进行实体识别时发生错误: {e}")
#         return []
#
# def rerank_regulations_with_vlm(description: str, regulations: list) -> list:
#     """
#     使用VLM对候选规范列表进行重排序。
#
#     Args:
#         description: 用户输入的问题描述。
#         regulations: 从向量搜索中获得的候选规范列表。
#
#     Returns:
#         一个根据VLM评分排序后的规范列表。
#     """
#     if not regulations:
#         return []
#
#     # 新增一个内部函数用于净化文本
#     def sanitize_text(text: str) -> str:
#         """移除可能导致VLM服务器出错的控制字符和多余空格"""
#         if not isinstance(text, str):
#             return ""
#         # 1. 移除所有Unicode控制字符 (C0 and C1 control codes)
#         # \x00-\x1F (C0), \x7F (DEL), \x80-\x9F (C1)
#         text = re.sub(r'[\x00-\x1F\x7F-\x9F]', ' ', text)
#         # 2. 将所有类型的空白符（包括换行、不间断空格等）替换为单个普通空格
#         text = re.sub(r'\s+', ' ', text)
#         # 3. 移除首尾空格
#         return text.strip()
#
#     max_rerank_count = 30  # 只对前30个进行重排序
#     if len(regulations) > max_rerank_count:
#         # 先取前30个进行重排序，其余保持原序
#         to_rerank = regulations[:max_rerank_count]
#         remaining = regulations[max_rerank_count:]
#     else:
#         to_rerank = regulations
#         remaining = []
#
#     # 构建提示，要求模型对每个规范进行评分
#     # 在构建Prompt时，对所有外部文本进行净化
#     clean_description = sanitize_text(description)
#     prompt_parts = [f"你是一个电力技术监督专家。请根据以下问题描述，评估每一条技术监督规范的相关性，并按从0到100的相关性分数进行打分。请严格按照'【规范ID】: [分数]'的格式输出，每个规范一行。\n\n问题描述：\n---\n{clean_description}\n---\n\n候选规范列表：\n"]
#     for i, reg in enumerate(to_rerank):
#         # 对每个字段都进行净化
#         title = sanitize_text(reg.get('title', ''))
#         basis = sanitize_text(reg.get('basis', ''))
#         points = sanitize_text(reg.get('points', ''))
#         requirements = sanitize_text(reg.get('requirements', ''))
#         reg_text = f"标题: {title}\n监督依据: {basis}\n监督要点: {points}\n监督要求: {requirements}"
#         prompt_parts.append(f"【规范{i}】:\n{reg_text}\n")
#
#     full_prompt = "".join(prompt_parts)
#
#     messages = [{'role': 'user', 'content': full_prompt}]
#
#     try:
#         response = call_vlm_api(messages, temperature=0.2)
#         content = response['choices'][0]['message']['content']
#     except Exception as e:
#         print(f"调用VLM进行重排时出错: {e}")
#         # 如果VLM失败，则返回原始列表，避免整个流程失败
#         return regulations
#
#     # 解析VLM的评分结果
#     scores = {}
#     score_matches = re.findall(r'【规范(\d+)】\s*[:：]\s*(\d+)', content)
#     for reg_id, score in score_matches:
#         try:
#             scores[int(reg_id)] = int(score)
#         except (ValueError, IndexError):
#             continue
#
#     # 将分数附加到原始规范对象上，并处理未被评分的规范
#     for i, reg in enumerate(to_rerank):
#         reg['vlm_score'] = scores.get(i, 0)
#         reg['final_score'] = reg['vlm_score'] + reg.get('score', 0) * 0.1
#
#     # 根据最终分数进行降序排序
#     # regulations.sort(key=lambda x: x.get('final_score', 0), reverse=True)
#
#     # return regulations
#     to_rerank.sort(key=lambda x: x.get('final_score', 0), reverse=True)
#
#     return to_rerank + remaining
