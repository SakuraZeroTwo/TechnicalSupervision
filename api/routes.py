from flask import Blueprint, request, jsonify, current_app, send_from_directory
from werkzeug.utils import secure_filename
import os
import json

# 导入服务
from services.vlm_service import get_vlm_analysis
from services.neo4j_service import neo4j_service
from services.word_service import create_word_report

# 创建一个蓝图
api_bp = Blueprint('api', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}


def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@api_bp.route('/analyze', methods=['POST'])
def analyze_issue():
    """
    核心功能端点：接收图片和描述，返回完整分析和报告链接
    """
    # 1. 检查文件和表单数据
    if 'image' not in request.files:
        return jsonify({"error": "请求中未找到图片文件"}), 400

    description = request.form.get('description', '')
    if not description:
        return jsonify({"error": "请求中未找到问题描述"}), 400

    file = request.files['image']
    if file.filename == '' or not allowed_file(file.filename):
        return jsonify({"error": "无效的图片文件"}), 400

    # 2. 保存上传的图片
    filename = secure_filename(file.filename)
    image_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    file.save(image_path)

    # 3. 调用 VLM 服务进行分析
    # 构建一个更复杂的 prompt，指导 VLM 按需输出
    prompt = f"""
    你是一个资深的电力设备巡检专家。请根据以下用户描述和图片，完成以下任务：
    1.  **状态描述**: 详细描述设备的状态，判断严重程度（例如：一般、严重）。
    2.  **原因分析**: 分析可能导致该问题的潜在原因。
    3.  **相关条例**: 从你的知识库中，列出与此问题相关的技术监督条例或安全规程（例如：DL/T 596-2021）。
    4.  **监督意见**: 提出具体的处理建议或监督意见。
    5.  **实体提取**: 识别描述和图片中的核心实体（例如：设备名称、问题类型、部件）。

    请将你的回答以 JSON 格式返回，包含以下键：'status_description', 'cause_analysis', 'regulations', 'supervision_suggestion', 'entities'。

    用户描述: "{description}"
    """
    vlm_result = get_vlm_analysis(prompt, image_path)

    if "error" in vlm_result:
        return jsonify({"error": "调用VLM模型失败", "details": vlm_result.get('error')}), 500

    # 4. 解析 VLM 返回的 JSON 结果
    try:
        raw_content = vlm_result['content']

        # 清理模型返回的字符串 ---
        # 模型可能返回被 Markdown 包裹的 JSON，例如 ```json\n{...}\n```，需要提取出纯净的 JSON 字符串
        if '```' in raw_content:
            # 找到第一个 '{' 和最后一个 '}' 来提取 JSON 对象
            start_index = raw_content.find('{')
            end_index = raw_content.rfind('}')
            if start_index != -1 and end_index != -1:
                json_string = raw_content[start_index:end_index + 1]
            else:
                json_string = raw_content  # 如果找不到，则按原样尝试
        else:
            json_string = raw_content

        analysis_content = json.loads(json_string)
    except (json.JSONDecodeError, KeyError) as e:
        return jsonify(
            {"error": "解析VLM返回结果失败", "details": str(e), "raw_vlm_output": vlm_result.get('content')}), 500

    # 5. 基于提取的实体查询 Neo4j
    entities_data = analysis_content.get('entities', {})
    # 确保我们处理的是一个列表
    entities_list = []
    if isinstance(entities_data, dict):
        # 如果实体是字典，我们可以提取它的值
        for key, value in entities_data.items():
            if isinstance(value, list):
                entities_list.extend(value)
            else:
                entities_list.append(value)
    elif isinstance(entities_data, list):
        entities_list = entities_data

    historical_cases = []
    subgraph = None

    try:
        if entities_list and entities_list[0]:
            historical_cases = neo4j_service.find_historical_cases(entities_list[0])
        # 任务5：尝试获取相关子图
        if entities_list:
            subgraph = neo4j_service.get_subgraph_for_entities(entities_list)
    except Exception as e:
        current_app.logger.error(f"Neo4j查询错误: {str(e)}")
        historical_cases = []
        subgraph = None


    # 6. 生成 Word 报告
    report_data = {
        'description': description,
        'analysis': analysis_content.get('cause_analysis'),
        'suggestions': analysis_content.get('supervision_suggestion'),
        'regulations': analysis_content.get('regulations')
    }
    report_path = create_word_report(report_data, image_path)
    report_url = request.host_url + 'api/static/reports/' + os.path.basename(report_path)

    # 7. 组合最终响应
    final_response = {
        "vlm_analysis": analysis_content,
        "historical_cases": historical_cases,
        "subgraph": subgraph,  # 新增子图数据
        "report_url": report_url
    }

    return jsonify(final_response)


@api_bp.route('/static/reports/<filename>')
def download_report(filename):
    """提供 Word 报告的下载链接"""
    # 注意：这里的路径需要和服务端保存的路径一致
    reports_folder = os.path.abspath(os.path.join('static', 'reports'))
    return send_from_directory(reports_folder, filename, as_attachment=True)