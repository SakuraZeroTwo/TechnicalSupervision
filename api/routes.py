from flask import Blueprint, request, jsonify, current_app, url_for, send_from_directory
from werkzeug.utils import secure_filename
import os
import json
import re  # 导入正则表达式库用于清洗数据

# 导入项目中定义好的服务函数和单例对象
from services.vlm_service import get_vlm_analysis
from services.word_service import create_word_report
from services.neo4j_service import neo4j_service
from services.regulation_service import regulation_service

# 创建API蓝图
api_bp = Blueprint('api', __name__)

# 定义允许上传的文件扩展名
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}


def allowed_file(filename):
    """
    检查上传的文件扩展名是否在允许的范围内。
    """
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def clean_json_from_vlm(response_str: str) -> str:
    """
    从VLM返回的可能包含Markdown的字符串中提取纯净的JSON部分。
    """
    # 使用正则表达式查找被 ```json ... ``` 包裹的内容
    match = re.search(r"```json\s*([\s\S]*?)\s*```", response_str)
    if match:
        return match.group(1).strip()

    # 如果没有匹配到Markdown，但可能有多余的空格或换行，直接strip
    return response_str.strip()


@api_bp.route('/analyze', methods=['POST'])
def analyze_issue():
    """
    接收图片和描述，进行智能分析，并返回结果和报告。
    """
    # 1. 验证请求中是否包含必要的数据
    if 'image' not in request.files:
        return jsonify({"error": "请求中未找到图片文件(image part)"}), 400

    description = request.form.get('description', '')
    if not description:
        return jsonify({"error": "请求中未找到问题描述(description)"}), 400

    file = request.files['image']

    # 2. 验证并保存上传的图片文件
    if file.filename == '':
        return jsonify({"error": "未选择任何文件"}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        upload_folder = current_app.config.get('UPLOAD_FOLDER', 'static/uploads')
        image_path = os.path.join(upload_folder, filename)
        file.save(image_path)
    else:
        return jsonify({"error": "不支持的文件类型，请上传 'png', 'jpg', 'jpeg', 'gif' 格式的图片"}), 400

    # 3. 调用条例检索服务
    try:
        stage_name = request.form.get('stage_name')
        top_clauses = regulation_service.find_relevant_clauses(description, stage_name=stage_name, top_n=30)
    except Exception as e:
        current_app.logger.error(f"条例细则检索失败: {str(e)}")
        top_clauses = []

    # 4. 构建用于VLM分析的Prompt
    clauses_text = "\n".join([f"备选项 {i + 1}: {clause.get('监督要点', '')}" for i, clause in enumerate(top_clauses)]) \
        if top_clauses else "未找到相关条例细则。"

    prompt = f"""
    你是一个资深的电力设备巡检专家。请根据用户描述和图片，并从我提供的“备选条例细则列表”中，选出最相关的几条，完成以下任务：
    1. **状态描述**: 详细描述图片中设备的状态。
    2. **原因分析**: 分析可能导致该问题的潜在原因。
    3. **相关条例**: 从下面的“备选条例细则列表”中，精选出不超过5条与问题最直接相关的条例。如果备选列表为空或都不相关，请依靠你自己的知识库。
    4. **监督意见**: 提出具体的处理建议或监督意见。
    5. **实体提取**: 识别描述和图片中的核心实体，用于知识图谱查询。

    请将你的回答以严格的 JSON 格式返回，包含以下键：'status_description', 'cause_analysis', 'regulations', 'supervision_suggestion', 'entities'。

    ---
    用户描述: "{description}"
    ---
    备选条例细则列表:
    {clauses_text}
    ---
    """

    # 5. 调用VLM服务并清洗返回结果
    vlm_response_str = get_vlm_analysis(prompt, image_path).get("content", "{}")

    # <-- 这里是关键的修正 -->
    clean_json_str = clean_json_from_vlm(vlm_response_str)
    # <-- 修正结束 -->

    try:
        # 使用清洗后的字符串进行JSON解析
        analysis_data = json.loads(clean_json_str)
    except json.JSONDecodeError:
        current_app.logger.error(f"VLM返回的不是有效的JSON, 清理后仍解析失败: {clean_json_str}")
        analysis_data = {}

    # 6. 查询知识图谱
    entities = analysis_data.get('entities', [])
    historical_cases = []
    subgraph = {}
    if entities:
        historical_cases = neo4j_service.find_historical_cases(keyword=entities[0])
        subgraph = neo4j_service.get_subgraph_for_entities(entities=entities)

    # 7. 生成Word报告
    try:
        report_data_for_word = {
            'description': description,
            'analysis': analysis_data.get('cause_analysis', '无'),
            'suggestions': analysis_data.get('supervision_suggestion', '无'),
            'regulations': analysis_data.get('regulations', [])  # 确保传入列表
        }
        report_path = create_word_report(report_data_for_word, image_path)
        report_filename = os.path.basename(report_path)
        report_url = url_for('api.download_report', filename=report_filename, _external=True)
    except Exception as e:
        current_app.logger.error(f"生成Word报告失败: {str(e)}")
        report_url = None

    # 8. 构造最终返回给前端的JSON响应
    final_response = {
        "retrieved_clauses": top_clauses,
        "vlm_analysis": analysis_data,
        "historical_cases": [dict(case) for case in historical_cases],
        "subgraph": [dict(node) for node in subgraph],
        "report_url": report_url
    }

    return jsonify(final_response)


@api_bp.route('/reports/<filename>')
def download_report(filename):
    """
    提供Word报告的下载接口。
    """
    directory = os.path.abspath(os.path.join('static', 'reports'))
    return send_from_directory(directory, filename, as_attachment=True)
