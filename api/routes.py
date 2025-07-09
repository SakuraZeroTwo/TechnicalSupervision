import jieba
from flask import Blueprint, request, jsonify, current_app, send_from_directory
from werkzeug.utils import secure_filename
import os
import json
import warnings
import re
import uuid

# 忽略openpyxl的样式警告
warnings.filterwarnings("ignore", category=UserWarning,
                        message="Workbook contains no default style, apply openpyxl's default")

# 导入服务
from services.neo4j_service import neo4j_service # neo4j服务已不再使用
from services.vlm_service import get_vlm_analysis, get_vlm_entities
from services.word_service import create_word_report
from services.file_service import file_service
from services.vlm_service import rerank_regulations_with_vlm
from urllib.parse import unquote

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
    entities_list = analysis_content.get('entities', [])
    if isinstance(entities_list, str):
        entities_list = [e.strip() for e in entities_list.split(',') if e.strip()]
    recognized_stage = stage

    # 添加原始描述中的关键词作为实体
    description_keywords = [w for w in jieba.lcut(description) if len(w) >= 2]
    for kw in description_keywords:
        if kw not in entities_list:
            entities_list.append(kw)

    # 6. 使用文件服务检索规范条例
    clean_stage = recognized_stage.replace("阶段", "") if recognized_stage else None
    # 【第一阶段：向量召回】从 file_service 获取一个较大的候选集
    candidate_regulations = file_service.find_regulations_by_stage_and_keywords(
        stage=clean_stage,
        keywords=description,
        max_results=100,  # 获取100个候选
        strict_stage_match=True,
        specific_file=specific_file,
        use_vector_search=True
    )
    # 确保返回的条例其文件名至少包含一个核心实体
    if entities_list and candidate_regulations:
        filtered_by_entity = []
        for reg in candidate_regulations:
            # 检查条例的标题（文件名）是否包含任何一个实体
            if any(entity in reg.get('title', '') for entity in entities_list):
                filtered_by_entity.append(reg)

        # 如果过滤后有结果，则使用过滤后的结果；否则，为避免无结果返回，使用原始候选集
        if filtered_by_entity:
            candidate_regulations = filtered_by_entity

    # 【第二阶段：VLM重排】调用VLM服务对候选集进行智能排序
    try:
        ranked_regulations = rerank_regulations_with_vlm(description, candidate_regulations)
    except Exception as e:
        current_app.logger.error(f"VLM重排失败: {e}")
        # 如果重排失败，则使用原始向量搜索结果
        ranked_regulations = candidate_regulations


    # 7. 直接选用第一条检索到的条例
    best_regulation = {}
    if ranked_regulations:
        # file_service 返回的结果已经按相关性排序，直接取第一个即可
        best_regulation = ranked_regulations[0]

    # 如果用户未指定阶段，但找到了匹配的规范，则从规范中回填阶段信息
    if not recognized_stage or recognized_stage is None:
        # 从规范的源数据中提取阶段，并确保它是一个非空字符串
        inferred_stage = best_regulation.get('source', {}).get('sheet')
        if inferred_stage:
            recognized_stage = inferred_stage
            current_app.logger.info(f"从匹配的规范 '{best_regulation.get('title')}' 中推断出阶段: {recognized_stage}")

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
        "regulations": ranked_regulations[:5], # 返回检索到的5条得分最高的条例供前端选择
        "report_url": None
    }

    # 10. 如果需要生成Word报告
    if generate_word:
        word_report_data = {
            'case_name': '待补充',
            'supervision_stage': recognized_stage,
            'regulation': best_regulation,
            'description': description,
            'expanded_description': analysis_content.get('expanded_description', '无扩写描述'),
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
            # 1. 从规范数据中获取大项名称和监督项目序号
            major_item = best_regulation.get('major_item_name', '')
            super_num = str(best_regulation.get('supervision_number', '')).strip()

            # 2. 从大项名称中提取开头的数字 (例如 "1.1 电气主接线")
            major_num_match = re.match(r'^(\d+(?:\.\d+)*)', major_item)
            major_num = major_num_match.group(1) if major_num_match else ''

            # 3. 拼接成新的条款序号
            if major_num and super_num:
                # 确保监督项目序号不是纯数字0
                if super_num != '0':
                    clause_no = f"{major_num}.{super_num}"
                else:
                    clause_no = major_num
            elif major_num:
                clause_no = major_num
            else:
                clause_no = super_num or '未知'

            # 4. 将组合好的条款序号写入报告数据
            word_report_data['regulation']['clause'] = clause_no

        report_path = create_word_report(word_report_data, image_path)
        report_url = request.host_url + 'static/reports/' + os.path.basename(report_path)
        final_response["report_url"] = report_url

    # 11. 【新增】缓存上下文用于重新生成
    task_id = str(uuid.uuid4())
    current_app.cache[task_id] = {
        "description": description,
        "image_path": image_path,
        "analysis_content": analysis_content,
        "ranked_regulations": ranked_regulations,
        "recognized_stage": recognized_stage,
        "generate_word": generate_word
    }
    final_response["task_id"] = task_id

    return jsonify(final_response)


@api_bp.route('/regenerate', methods=['POST'])
def regenerate_analysis_and_report():
    """
    根据用户从列表中选择的新细则，重新生成分析和报告。
    """
    data = request.get_json()
    task_id = data.get('task_id')
    selected_regulation = data.get('selected_regulation')

    if not task_id or not selected_regulation:
        return jsonify({"error": "缺少 task_id 或 selected_regulation"}), 400

    # 1. 从缓存中获取原始上下文
    cached_data = current_app.cache.get(task_id)
    if not cached_data:
        return jsonify({"error": "任务已过期或无效"}), 404

    description = cached_data['description']
    image_path = cached_data['image_path']
    analysis_content = cached_data['analysis_content']
    recognized_stage = cached_data['recognized_stage']
    generate_word = cached_data['generate_word']

    # 2. 准备新的前端展示数据
    display_data = {
        "description": {
            "title": "问题描述",
            "content": description
        },
        "regulation_details": {
            "title": "依据细则",
            "content": f"**细则名称**: {selected_regulation.get('title', '未匹配到细则')}\n\n"
                       f"**监督依据**: {selected_regulation.get('basis', '无')}"
        },
        "supervision_standard": {
            "title": "监督标准",
            "content": selected_regulation.get('points', '根据上述细则进行监督')
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

    # 3. 准备最终响应
    final_response = {
        "display_data": display_data,
        "report_url": None
    }

    # 4. 如果需要，重新生成Word报告
    if generate_word:
        word_report_data = {
            'case_name': '待补充',
            'supervision_stage': recognized_stage,
            'regulation': selected_regulation,
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

        if selected_regulation:
            major_item = selected_regulation.get('major_item_name', '')
            super_num = str(selected_regulation.get('supervision_number', '')).strip()
            major_num_match = re.match(r'^(\d+(?:\.\d+)*)', major_item)
            major_num = major_num_match.group(1) if major_num_match else ''

            if major_num and super_num and super_num != '0':
                clause_no = f"{major_num}.{super_num}"
            elif major_num:
                clause_no = major_num
            else:
                clause_no = super_num or '未知'
            word_report_data['regulation']['clause'] = clause_no

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
    """提供历史案例文档的下载"""
    try:
        # 完全解码文件名，处理URL中的特殊字符
        decoded_filename = unquote(filename)

        # 从 file_service 获取案例文件存放的目录
        case_directory = file_service.cases_path

        # 使用 send_from_directory 安全地发送文件
        return send_from_directory(case_directory, decoded_filename, as_attachment=True)
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