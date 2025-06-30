import jieba
from flask import Blueprint, request, jsonify, current_app, send_from_directory
from werkzeug.utils import secure_filename
import os
import json
import warnings

# 忽略openpyxl的样式警告
warnings.filterwarnings("ignore", category=UserWarning,
                        message="Workbook contains no default style, apply openpyxl's default")

# 导入服务
from services.vlm_service import get_vlm_analysis
# from services.neo4j_service import neo4j_service # neo4j服务已不再使用
from services.word_service import create_word_report
from services.file_service import file_service
from utils.format_converter import prepare_report_data_for_word, prepare_report_data_for_frontend

# 创建一个蓝图
api_bp = Blueprint('api', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}


def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@api_bp.route('/analyze', methods=['POST'])
def analyze_issue():
    """
    核心功能端点：接收图片、描述和阶段，返回完整分析和报告链接
    """
    # 1. 检查文件和表单数据
    if 'image' not in request.files:
        return jsonify({"error": "请求中未找到图片文件"}), 400

    description = request.form.get('description', '')
    if not description:
        return jsonify({"error": "请求中未找到问题描述"}), 400

    # 获取阶段参数
    stage = request.form.get('stage', None)

    file = request.files['image']
    if file.filename == '' or not allowed_file(file.filename):
        return jsonify({"error": "无效的图片文件"}), 400

    # 2. 保存上传的图片
    filename = secure_filename(file.filename)
    image_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    file.save(image_path)

    # 3. 调用 VLM 服务进行分析,传入阶段参数
    vlm_result = get_vlm_analysis(description, image_path, stage)

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

    # 5. 从分析中提取关键信息
    entities_list = []
    entities_data = analysis_content.get('entities', [])
    if isinstance(entities_data, list):
        entities_list = entities_data
    elif isinstance(entities_data, str):
        entities_list = [e.strip() for e in entities_data.split(',')]

    # 添加原始描述中的关键词作为实体
    if description:
        description_keywords = [w for w in jieba.lcut(description) if len(w) >= 2]
        for kw in description_keywords:
            if kw not in entities_list:
                entities_list.append(kw)

    recognized_stage = analysis_content.get('stage', stage if stage else '运维检修阶段')
    enhanced_description = analysis_content.get('enhanced_description', description)  # 获取扩写后的描述

    # 6. 使用文件服务检索规范条例
    retrieved_regulations = []
    if entities_list:
        try:
            clean_stage = recognized_stage.replace("阶段", "") if recognized_stage else "运维检修"
            retrieved_regulations = file_service.find_regulations_by_stage_and_keywords(clean_stage, entities_list)
        except Exception as e:
            current_app.logger.error(f"文件检索错误: {str(e)}")

    # 7. 【最终简化逻辑】直接选用第一条检索到的条例
    best_regulation = {}
    if retrieved_regulations:
        # file_service 返回的结果已经按相关性排序，直接取第一个即可
        best_regulation = retrieved_regulations[0]

    # 8. 准备 Word 报告所需的数据 (精确、简化)
    word_report_data = {
        'stage': recognized_stage,
        'regulation': best_regulation,  # 传递选出的最佳条例字典
        'description': enhanced_description,  # 使用扩写后的描述
        'analysis': analysis_content.get('cause_analysis', ''),
        'suggestions': analysis_content.get('supervision_suggestion', ''),
    }

    # 9. 生成 Word 报告
    report_path = create_word_report(word_report_data, image_path)
    report_url = request.host_url + 'api/static/reports/' + os.path.basename(report_path)

    # 10. 组合最终响应
    final_response = {
        "vlm_analysis": analysis_content,
        "historical_cases": file_service.find_historical_cases_by_entities(entities_list, recognized_stage),
        "regulations": [best_regulation] if best_regulation else [],  # 返回给前端的也只是最佳条例
        "subgraph": file_service.get_subgraph_for_entities(entities_list),
        "report_url": report_url
    }

    return jsonify(final_response)


# 添加阶段获取端点
@api_bp.route('/stages', methods=['GET'])
def get_available_stages():
    """获取系统中所有可用的阶段列表"""
    stages = [
        "规划可研阶段",
        "工程设计阶段",
        "设备采购阶段",
        "设备制造阶段",
        "设备验收阶段",
        "设备安装阶段",
        "设备调试阶段",
        "竣工验收阶段",
        "运维检修阶段",
        "退役报废阶段"
    ]
    return jsonify({"stages": stages})


# 添加单独的案例检索端点
@api_bp.route('/search/cases', methods=['POST'])
def search_historical_cases():
    """根据关键词和可选阶段搜索历史案例"""
    data = request.json

    if not data or 'keywords' not in data:
        return jsonify({"error": "请提供搜索关键词"}), 400

    keywords = data.get('keywords', [])
    stage = data.get('stage', None)

    try:
        results = file_service.find_historical_cases_by_entities(keywords, stage)
        return jsonify({"cases": results})
    except Exception as e:
        return jsonify({"error": f"搜索失败: {str(e)}"}), 500


@api_bp.route('/static/reports/<filename>')
def download_report(filename):
    """提供 Word 报告的下载链接"""
    reports_folder = os.path.abspath(os.path.join('static', 'reports'))
    return send_from_directory(reports_folder, filename, as_attachment=True)
