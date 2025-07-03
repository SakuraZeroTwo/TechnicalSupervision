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
    # 1. 检查表单数据

    description = request.form.get('description', '')
    if not description:
        return jsonify({"error": "请求中未找到问题描述"}), 400

    # 获取阶段参数
    stage = request.form.get('stage', None)

    # 获取指定细则参数
    specific_file = request.form.get('specific_file', None)

    # 是否生成报告
    generate_word = request.form.get('generate_word', 'true').lower() == 'true'

    # 2.处理可选的图片
    image_path = None
    if 'image' in request.files and request.files['image'].filename:
        file = request.files['image']
        if file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            image_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            file.save(image_path)
        elif file.filename != '':
            return jsonify({"error": "无效的图片文件"}), 400

    # 3. 调用 VLM 服务进行分析,传入阶段参数
    vlm_result = get_vlm_analysis(description, image_path, stage)
    if "error" in vlm_result:
        return jsonify({"error": "调用VLM模型失败", "details": vlm_result.get('error')}), 500

    # 4. 解析 VLM 返回的 JSON 结果
    try:
        raw_content = vlm_result['content']
        # 清理模型可能返回的 Markdown 代码块
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

    # 5. 直接从原始描述中提取关键词作为实体
    entities_list = [word for word in jieba.lcut(description) if len(word) >= 2]

    # 从VLM结果中获取阶段和分析，但描述使用原始描述
    recognized_stage = analysis_content.get('stage', stage if stage else '运维检修阶段')

    # 添加原始描述中的关键词作为实体
    if description:
        description_keywords = [w for w in jieba.lcut(description) if len(w) >= 2]
        for kw in description_keywords:
            if kw not in entities_list:
                entities_list.append(kw)

    # 6. 使用文件服务检索规范条例
    retrieved_regulations = []
    if entities_list:
        try:
            clean_stage = recognized_stage.replace("阶段", "") if recognized_stage else "运维检修"
            retrieved_regulations = file_service.find_regulations_by_stage_and_keywords(clean_stage, entities_list, strict_stage_match=True, specific_file=specific_file,use_vector_search=True)
        except Exception as e:
            current_app.logger.error(f"文件检索错误: {str(e)}")

    # 7. 直接选用第一条检索到的条例
    best_regulation = {}
    if retrieved_regulations:
        # file_service 返回的结果已经按相关性排序，直接取第一个即可
        best_regulation = retrieved_regulations[0]

    # 8. 准备用于前端展示的结构化数据
    display_data = {
        "description": {
            "title": "问题描述",
            "content": description
        },
        "regulation_details": {
            "title": "依据细则",
            "content": f"**细则名称**: {best_regulation.get('title', '未匹配到细则')}\n\n"
                       f"**监督依据**: {best_regulation.get('basis', '无')}"
        },
        "supervision_standard": {
            "title": "监督标准",
            "content": best_regulation.get('points', '根据上述细则进行监督')
        },
        "cause_analysis": {
            "title": "原因分析",
            "content": analysis_content.get('cause_analysis', '暂无分析')
        },
        "supervision_suggestion": {
            "title": "监督意见",
            "content": analysis_content.get('supervision_suggestion', '暂无建议')
        }
    }

    # 获取历史案例并为其添加下载链接
    historical_cases = file_service.find_historical_cases_by_entities(entities_list, recognized_stage, strict_stage_match=True)
    for case in historical_cases:
        if 'source' in case:
            # 构建完整的下载URL
            case['download_url'] = f"{request.host_url}api/download/case/{case['source']}"

    # 9. 准备最终响应
    final_response = {
        "display_data": display_data,
        "historical_cases":  historical_cases,
        "regulations": retrieved_regulations, # 返回所有检索到的条例供前端选择
        "report_url": None
    }

    # 10. 如果需要生成Word报告
    if generate_word:
        word_report_data = {
            'case_name': f"{recognized_stage} - {entities_list[0] if entities_list else '通用'}问题案例",
            'supervision_stage': recognized_stage,
            'regulation': best_regulation,
            'description': description,
            'analysis': analysis_content.get('cause_analysis', '待补充'),
            'suggestions': analysis_content.get('supervision_suggestion', '待补充'),
            # 其他字段可以根据需要填充
            'unit_name': '待补充',
            'project_info': {},
            'device_info': {},
            'supervision_major': '待补充',
            'discovery_date': '待补充',
            'rectification_measures': '待补充',
            'other_issues': '无',
            'attachments': '无'
        }
        report_path = create_word_report(word_report_data, image_path)
        report_url = request.host_url + 'static/reports/' + os.path.basename(report_path)
        final_response["report_url"] = report_url

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


@api_bp.route('/search/cases', methods=['POST'])
def search_historical_cases():
    """根据实体和阶段检索历史案例"""
    data = request.get_json()
    entities = data.get('entities', [])
    stage = data.get('stage', None)

    if not entities:
        return jsonify({"error": "实体列表不能为空"}), 400

    cases = file_service.find_historical_cases_by_entities(entities, stage)
    # 下载链接
    for case in cases:
        if 'source' in case:
            case['download_url'] = f"{request.host_url}api/download/case/{case['source']}"
    return jsonify(cases)


# 案例文件下载端点
@api_bp.route('/download/case/<path:filename>', methods=['GET'])
def download_case_file(filename):
    """提供历史案例文档的下载"""
    try:
        # 从 file_service 获取案例文件存放的目录
        case_directory = file_service.cases_path
        # 使用 send_from_directory 安全地发送文件
        return send_from_directory(case_directory, filename, as_attachment=True)
    except FileNotFoundError:
        return jsonify({"error": "文件未找到"}), 404
    except Exception as e:
        current_app.logger.error(f"下载案例文件时出错: {e}")
        return jsonify({"error": "服务器内部错误"}), 500