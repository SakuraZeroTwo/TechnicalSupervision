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

from services.regulation_service import regulation_service  # 确保导入的是新服务


# ... (保留蓝图定义和 allowed_file 函数)

@api_bp.route('/analyze', methods=['POST'])
def analyze_issue():
    # 1. 检查文件和表单数据
    if 'image' not in request.files:
        return jsonify({"error": "请求中未找到图片文件"}), 400

    description = request.form.get('description', '')
    if not description:
        return jsonify({"error": "请求中未找到问题描述"}), 400

    # <-- 新增：获取可选的阶段名 -->
    stage_name = request.form.get('stage_name', None)

    file = request.files['image']
    # ... (保留文件合法性检查)

    # 2. 保存上传的图片
    # ... (保留保存图片的逻辑)

    # 3. 调用新的 RegulationService 进行细粒度检索
    try:
        # 调用新函数，传入 description 和可选的 stage_name
        top_clauses = regulation_service.find_relevant_clauses(description, stage_name=stage_name, top_n=30)
    except Exception as e:
        current_app.logger.error(f"条例细则检索失败: {str(e)}")
        top_clauses = []

    # 4. 构建包含30条备选细则的 Prompt，让大模型精选
    clauses_text = ""
    if top_clauses:
        # 将30条备选细则格式化为清晰的列表
        clauses_list = [f"备选项 {i + 1}: {clause.get('监督要点', '')}" for i, clause in enumerate(top_clauses)]
        clauses_text = "\n".join(clauses_list)
    else:
        clauses_text = "未找到相关条例细则。"

    prompt = f"""
    你是一个资深的电力设备巡检专家。请根据用户描述和图片，并从我提供的“备选条例细则列表”中，选出最相关的几条，完成以下任务：
    1.  **状态描述**: 详细描述设备的状态。
    2.  **原因分析**: 分析可能导致该问题的潜在原因。
    3.  **相关条例**: 从下面的“备选条例细则列表”中，精选出不超过5条与问题最直接相关的条例。如果备选列表为空或都不相关，请依靠你自己的知识库。
    4.  **监督意见**: 提出具体的处理建议或监督意见。
    5.  **实体提取**: 识别描述和图片中的核心实体。

    请将你的回答以 JSON 格式返回，包含以下键：'status_description', 'cause_analysis', 'regulations', 'supervision_suggestion', 'entities'。

    ---
    用户描述: "{description}"
    ---
    备选条例细则列表:
    {clauses_text}
    ---
    """

    vlm_result = get_vlm_analysis(prompt, image_path)

    # ... (保留后续的 VLM 结果解析、Neo4j 查询、Word 报告生成和最终响应组合逻辑)
    # 可以在最终响应中加入检索到的细则，方便前端展示或调试
    final_response = {
        "retrieved_clauses": top_clauses,  # <-- 新增或替换为检索到的细则
        "vlm_analysis": frontend_analysis,
        "historical_cases": historical_cases,
        "subgraph": subgraph,
        "report_url": report_url
    }

    return jsonify(final_response)

@api_bp.route('/static/reports/<filename>')
def download_report(filename):
    """提供 Word 报告的下载链接"""
    # 注意：这里的路径需要和服务端保存的路径一致
    reports_folder = os.path.abspath(os.path.join('static', 'reports'))
    return send_from_directory(reports_folder, filename, as_attachment=True)