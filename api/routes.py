import jieba
from flask import Blueprint, request, jsonify, current_app, send_from_directory
from werkzeug.utils import secure_filename
import os
import json
import warnings
import re
import uuid

warnings.filterwarnings("ignore", category=UserWarning,
                        message="Workbook contains no default style, apply openpyxl's default")

from services.vlm_service import get_vlm_analysis, get_vlm_entities
from services.neo4j_service import neo4j_service
from services.word_service import create_word_report
from services.file_service import file_service

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
    description = request.form.get('description', '')
    if not description:
        return jsonify({"error": "请求中未找到问题描述"}), 400

    stage = request.form.get('stage', None)
    specific_file = request.form.get('specific_file', None)
    generate_word = request.form.get('generate_word', 'true').lower() == 'true'

    image_path = None
    if 'image' in request.files and request.files['image'].filename:
        file = request.files['image']
        if file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            image_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            file.save(image_path)
        elif file.filename != '':
            return jsonify({"error": "无效的图片文件"}), 400

    vlm_result = get_vlm_analysis(description, image_path, stage)
    if "error" in vlm_result:
        return jsonify({"error": "调用VLM模型失败", "details": vlm_result.get('error')}), 500

    try:
        raw_content = vlm_result['content']
        if '```' in raw_content:
            start_index = raw_content.find('{')
            end_index = raw_content.rfind('}')
            if start_index != -1 and end_index != -1:
                json_string = raw_content[start_index:end_index + 1]
            else:
                json_string = raw_content
        else:
            json_string = raw_content
        analysis_content = json.loads(json_string)
    except (json.JSONDecodeError, KeyError) as e:
        return jsonify(
            {"error": "解析VLM返回结果失败", "details": str(e), "raw_vlm_output": vlm_result.get('content')}), 500

    entities_list = [word for word in jieba.lcut(description) if len(word) >= 2]
    recognized_stage = analysis_content.get('stage', stage if stage else '运维检修阶段')

    if description:
        description_keywords = [w for w in jieba.lcut(description) if len(w) >= 2]
        for kw in description_keywords:
            if kw not in entities_list:
                entities_list.append(kw)

    retrieved_regulations = []
    if entities_list:
        try:
            clean_stage = recognized_stage.replace("阶段", "") if recognized_stage else "运维检修"
            retrieved_regulations = file_service.find_regulations_by_stage_and_keywords(clean_stage, entities_list,
                                                                                        strict_stage_match=True,
                                                                                        specific_file=specific_file,
                                                                                        use_vector_search=True)
        except Exception as e:
            current_app.logger.error(f"文件检索错误: {str(e)}")

    best_regulation = {}
    if retrieved_regulations:
        best_regulation = retrieved_regulations[0]

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

    historical_cases = file_service.find_historical_cases_by_entities(entities_list, recognized_stage,
                                                                      strict_stage_match=True)
    for case in historical_cases:
        if 'source' in case:
            case['download_url'] = f"{request.host_url}api/download/case/{case['source']}"

    final_response = {
        "display_data": display_data,
        "historical_cases": historical_cases,
        "regulations": retrieved_regulations,
        "report_url": None
    }

    if generate_word:
        word_report_data = {
            'case_name': '待补充',
            'supervision_stage': recognized_stage,
            'regulation': best_regulation,
            'description': description,
            'analysis': analysis_content.get('cause_analysis', '待补充'),
            'suggestions': analysis_content.get('supervision_suggestion', '待补充'),
            'unit_name': '待补充',
            'project_info': {},
            'device_info': {},
            'supervision_major': '待补充',
            'discovery_date': '待补充',
            'rectification_measures': '待补充',
            'other_issues': '无',
            'attachments': '无'
        }

        if best_regulation:
            major_item_name = best_regulation.get('major_item_name', '')
            points_text = best_regulation.get('points', '')
            major_num_match = re.search(r'^(\d+(\.\d+)*)', major_item_name)
            points_num_match = re.search(r'^[（\(]?(\d+)[）\)\.、]*', points_text)
            major_num = major_num_match.group(1) if major_num_match else ''
            points_num = points_num_match.group(1) if points_num_match else ''

            if major_num and points_num:
                clause_number = f"{major_num}.{points_num}"
                word_report_data['regulation']['clause'] = clause_number
            elif major_num:
                word_report_data['regulation']['clause'] = major_num
            elif points_num:
                word_report_data['regulation']['clause'] = points_num
            else:
                word_report_data['regulation']['clause'] = "未知"

        report_path = create_word_report(word_report_data, image_path)
        report_url = request.host_url + 'static/reports/' + os.path.basename(report_path)
        final_response["report_url"] = report_url

    return jsonify(final_response)


@api_bp.route('/stages', methods=['GET'])
def get_available_stages():
    """获取系统中所有可用的阶段列表"""
    stages = [
        "规划可研阶段", "工程设计阶段", "设备采购阶段", "设备制造阶段", "设备验收阶段",
        "设备安装阶段", "设备调试阶段", "竣工验收阶段", "运维检修阶段", "退役报废阶段"
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
    for case in cases:
        if 'source' in case:
            case['download_url'] = f"{request.host_url}api/download/case/{case['source']}"
    return jsonify(cases)


@api_bp.route('/download/case/<path:filename>', methods=['GET'])
def download_case_file(filename):
    """提供历史案例文档的下载"""
    try:
        case_directory = file_service.cases_path
        return send_from_directory(case_directory, filename, as_attachment=True)
    except FileNotFoundError:
        return jsonify({"error": "文件未找到"}), 404
    except Exception as e:
        current_app.logger.error(f"下载案例文件时出错: {e}")
        return jsonify({"error": "服务器内部错误"}), 500


@api_bp.route('/generate_answer', methods=['POST'])
def generate_answer_and_cases():
    """
    【功能2 - 按钮1】的后端接口。
    接收描述，生成 Answer 和历史案例，并返回一个唯一的 task_id。
    """
    description = request.form.get('description', '')
    if not description:
        return jsonify({"error": "请求中未找到问题描述"}), 400

    try:
        vlm_result = get_vlm_analysis(description, image_path=None, stage=None)
        if "error" in vlm_result:
            return jsonify({"error": "调用VLM模型失败", "details": vlm_result.get('error')}), 500

        raw_content = vlm_result['content']
        json_string = raw_content
        if '```' in raw_content:
            start_index = raw_content.find('{')
            end_index = raw_content.rfind('}')
            if start_index != -1 and end_index != -1:
                json_string = raw_content[start_index:end_index + 1]

        analysis_content = json.loads(json_string)

    except (json.JSONDecodeError, KeyError) as e:
        return jsonify(
            {"error": "解析VLM返回结果失败", "details": str(e), "raw_vlm_output": vlm_result.get('content')}), 500

    answer = {
        "status_description": analysis_content.get('status_description', '暂无状态描述'),
        "cause_analysis": analysis_content.get('cause_analysis', '暂无原因分析'),
        "supervision_suggestion": analysis_content.get('supervision_suggestion', '暂无监督意见')
    }

    entities_list = analysis_content.get('entities', [])
    if not entities_list:
        entities_list = [word for word in jieba.lcut(description) if len(word) >= 2]

    historical_cases = file_service.find_historical_cases_by_entities(entities_list)
    for case in historical_cases:
        if 'source' in case:
            case['download_url'] = f"{request.host_url}api/download/case/{case['source']}"

    task_id = str(uuid.uuid4())
    cached_data = {
        "description": description,
        "analysis_text": answer.get('cause_analysis', '')
    }

    current_app.cache[task_id] = cached_data

    return jsonify({
        "task_id": task_id,
        "answer": answer,
        "historical_cases": historical_cases
    })


@api_bp.route('/graph', methods=['POST'])
def graph_analysis_from_text():
    """
    【功能2 - 按钮2】的后端接口。
    接收 description 和可选的 task_id，进行交叉验证后生成图谱。
    """
    description = request.form.get('description', '')
    if not description:
        return jsonify({"error": "问题描述(description)是必需的"}), 400

    task_id = request.form.get('task_id')

    analysis_text = ""
    use_context = False

    if task_id:
        task_data = current_app.cache.get(task_id)
        if task_data and task_data.get("description", "").strip() == description.strip():
            analysis_text = task_data.get("analysis_text", "")
            use_context = True

    if use_context:
        text_for_ner = description + " " + analysis_text
    else:
        text_for_ner = description

    try:
        entities_list = get_vlm_entities(text_for_ner)
        if not entities_list:
            return jsonify({"message": "未能识别出有效实体", "subgraph": {"nodes": [], "links": []}}), 200

        subgraph_data = neo4j_service.get_subgraph_for_entities(entities_list)

        return jsonify({
            "entities_found": entities_list,
            "subgraph": subgraph_data
        })
    except Exception as e:
        current_app.logger.error(f"图谱生成过程中出错: {e}")
        return jsonify({"error": "图谱生成过程中发生内部错误"}), 500
